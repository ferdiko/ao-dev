#!/usr/bin/env python3

import sys
import os
import json
import shlex
import random
import threading
import traceback
import time
import psutil
import signal
import runpy

from typing import Optional, List

from sovara.common.logger import logger
from sovara.common.constants import (
    HOST,
    PORT,
    SERVER_START_TIMEOUT,
    MESSAGE_POLL_INTERVAL,
)
from sovara.cli.so_server import launch_daemon_server
from sovara.common.project import ensure_project_configured
from sovara.server.database_manager import DB
from sovara.runner.context_manager import (
    clear_run_timer,
    reset_current_run_timer,
    set_parent_run_id,
)
from sovara.common.utils import set_server_url, http_post
from sovara.runner.monkey_patching.apply_monkey_patches import apply_all_monkey_patches


def _log_error(context: str, exception: Exception) -> None:
    """Centralized error logging utility."""
    logger.error(f"[AgentRunner] {context}: {exception}")
    logger.debug(f"[AgentRunner] Traceback: {traceback.format_exc()}")


def _find_process_on_port(port: int) -> Optional[int]:
    """Find PID of process listening on the given port using lsof."""
    import subprocess
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            pid_str = result.stdout.strip().split("\n")[0]
            return int(pid_str)
    except Exception as e:
        logger.debug(f"Could not check port {port} with lsof: {e}")
    return None


def _kill_zombie_server(pid: int) -> bool:
    """Kill a zombie server process gracefully."""
    try:
        os.kill(pid, signal.SIGTERM)
        logger.info(f"Sent SIGTERM to zombie server process {pid}")
        for _ in range(6):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except OSError:
                return True
        logger.warning(f"Process {pid} didn't respond to SIGTERM, sending SIGKILL")
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
        return True
    except OSError as e:
        if e.errno == 3:
            return True
        logger.warning(f"Could not kill process {pid}: {e}")
        return False


def _check_server_health() -> bool:
    """Check if the server is healthy via HTTP."""
    import httpx
    try:
        resp = httpx.get(f"http://{HOST}:{PORT}/health", timeout=SERVER_START_TIMEOUT)
        return resp.status_code == 200
    except Exception:
        return False


def ensure_server_running() -> None:
    """Ensure the server is running, start it if necessary."""
    if _check_server_health():
        logger.debug(f"Server already running on {HOST}:{PORT}")
        return

    # Check for zombie process
    zombie_pid = _find_process_on_port(PORT)
    if zombie_pid:
        logger.warning(f"Found unresponsive server process {zombie_pid}, killing it...")
        if _kill_zombie_server(zombie_pid):
            time.sleep(1)

    # Launch new daemon
    launch_daemon_server()
    logger.debug("Daemon launched, waiting for startup...")

    # Poll for server availability
    max_wait = 15
    poll_interval = 0.5
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval
        if _check_server_health():
            logger.info(f"Server started successfully after {elapsed:.1f}s")
            return

    # Final attempt
    if not _check_server_health():
        raise RuntimeError(f"Server not ready after {max_wait}s")
    logger.info("Server started successfully (final attempt)")


class AgentRunner:
    """Unified agent runner that combines orchestration and execution."""

    def __init__(
        self,
        script_path: str,
        script_args: List[str],
        is_module_execution: bool,
        sample_id: Optional[str] = None,
        run_name: Optional[str] = None,
    ):
        self.script_path = script_path
        self.script_args = script_args
        self.is_module_execution = is_module_execution
        self.sample_id = sample_id
        self.run_name = run_name

        # State management
        self.shutdown_flag = False
        self.restart_event = threading.Event()
        self.process_id = os.getpid()
        self._signal_count = 0
        self._deregister_sent = False

        # Run
        self.run_id: Optional[str] = None
        self.server_url: Optional[str] = None

        # SSE listener thread
        self.listener_thread: Optional[threading.Thread] = None

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Start computing restart command in background (it's slow due to psutil)
        from concurrent.futures import ThreadPoolExecutor
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._restart_command_future = self._executor.submit(self._generate_restart_command)

    def _signal_handler(self, signum, frame) -> None:
        """Handle termination signals gracefully."""
        self._signal_count += 1
        if self._signal_count > 1:
            os._exit(130)
        logger.info(f"Received signal {signum}, shutting down...")
        self.shutdown_flag = True
        self._send_deregister(timeout=0.5)
        clear_run_timer(self.run_id)
        raise SystemExit(130)

    def _send_deregister(self, timeout: float | None = None) -> None:
        """Send deregistration message to the server."""
        if self.run_id and not self._deregister_sent:
            try:
                http_post("/runner/deregister", {"run_id": self.run_id}, timeout=timeout)
                self._deregister_sent = True
            except Exception as e:
                _log_error("Failed to send deregister", e)

    def _listen_for_server_events(self) -> None:
        """Background thread: listen for SSE events from the server."""
        import httpx

        url = f"{self.server_url}/runner/events/{self.run_id}"
        try:
            with httpx.stream("GET", url, timeout=None) as resp:
                for line in resp.iter_lines():
                    if self.shutdown_flag:
                        break
                    if not line or line.startswith(":"):
                        continue  # keepalive or comment
                    if line.startswith("data: "):
                        try:
                            event = json.loads(line[6:])
                            self._handle_server_event(event)
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            if not self.shutdown_flag:
                _log_error("SSE connection lost", e)

    def _handle_server_event(self, event: dict) -> None:
        """Handle incoming server events."""
        event_type = event.get("type")
        if event_type == "restart":
            logger.info("[AgentRunner] Received restart event")
            self.restart_event.set()
        elif event_type == "shutdown":
            logger.info("[AgentRunner] Received shutdown event")
            self.shutdown_flag = True

    def _is_debugpy_session(self) -> bool:
        """Detect if we're running under debugpy (VSCode debugging)."""
        if os.environ.get("SOVARA_NO_DEBUG_MODE", False):
            return False
        if "debugpy" not in sys.modules:
            return False
        try:
            import debugpy
            return debugpy.is_client_connected() or hasattr(debugpy, "_client")
        except (ImportError, AttributeError):
            return True

    def _get_parent_cmdline(self) -> List[str]:
        """Get the command line of the parent process."""
        try:
            current_process = psutil.Process()
            parent = current_process.parent()
            return parent.cmdline() if parent else []
        except Exception as e:
            _log_error("Failed to get parent cmdline", e)
            return []

    def _generate_restart_command(self) -> str:
        """Generate the appropriate command for restarting the script."""
        original_command = " ".join(shlex.quote(arg) for arg in sys.argv)
        python_executable = sys.executable

        if not self._is_debugpy_session():
            return f"{python_executable} {original_command}"
        parent_cmdline = self._get_parent_cmdline()

        if not parent_cmdline:
            return f"/usr/bin/env {python_executable} {original_command}"

        cmdline_str = " ".join(shlex.quote(arg) for arg in parent_cmdline)

        if "launcher" in cmdline_str and "--" in parent_cmdline:
            dash_index = parent_cmdline.index("--")
            original_args = " ".join(shlex.quote(arg) for arg in parent_cmdline[dash_index + 1:])
            return f"/usr/bin/env {python_executable} {original_args}"

        if "-m" in parent_cmdline and "debugpy" in parent_cmdline:
            if self.is_module_execution:
                target_args = f"-m {self.script_path} {' '.join(shlex.quote(arg) for arg in self.script_args)}"
            else:
                target_args = f"{shlex.quote(self.script_path)} {' '.join(shlex.quote(arg) for arg in self.script_args)}"
            return f"{python_executable} {target_args}"

        if self.is_module_execution:
            target_args = f"-m {self.script_path} {' '.join(shlex.quote(arg) for arg in self.script_args)}"
        else:
            target_args = f"{shlex.quote(self.script_path)} {' '.join(shlex.quote(arg) for arg in self.script_args)}"
        return f"{python_executable} {target_args}"

    def _register_with_server(self) -> None:
        """Register with the server via HTTP POST."""
        logger.info(f"[AgentRunner] Registering with server at {self.server_url}...")

        response = http_post("/runner/register", {
            "name": self.run_name,
            "cwd": os.getcwd(),
            "environment": dict(os.environ),
            "prev_run_id": os.getenv("SOVARA_RUN_ID"),
            "project_id": self.project_id,
            "project_name": self.project_name,
            "project_description": self.project_description,
            "project_root": self.project_root,
            "user_id": self.user_id,
            "user_full_name": self.user_full_name,
            "user_email": self.user_email,
        })

        self.run_id = response.get("run_id")
        if not self.run_id:
            raise RuntimeError(f"Registration failed: {response}")
        logger.info(f"Registered with run_id: {self.run_id}")

        # Write run info to file for so-cli IPC
        run_file = os.environ.get("SOVARA_RUN_FILE")
        if run_file:
            try:
                with open(run_file, "w") as f:
                    json.dump({"run_id": self.run_id, "pid": self.process_id}, f)
            except Exception as e:
                logger.warning(f"Failed to write run file: {e}")

    def _setup_environment(self) -> None:
        """Set up the execution environment for the agent runner."""
        if os.environ.get("_SOVARA_TESTING"):
            from sovara.common.constants import TEST_USER_ID, TEST_PROJECT_ID
            self.user_id = TEST_USER_ID
            self.user_full_name = "Test User"
            self.user_email = "test@test.com"
            self.project_id = TEST_PROJECT_ID
            self.project_name = "sovara-test"
            self.project_description = ""
            self.project_root = os.getcwd()
        else:
            from sovara.common.user import ensure_user_configured
            user_config = ensure_user_configured()
            self.user_id = user_config["user_id"]
            self.user_full_name = user_config["full_name"]
            self.user_email = user_config["email"]

            script_dir = os.path.dirname(os.path.abspath(self.script_path))
            project_config = ensure_project_configured(self.user_id, script_dir)
            self.project_id = project_config["project_id"]
            self.project_name = project_config["name"]
            self.project_description = project_config["description"]
            self.project_root = project_config["project_root"]

        # Set random seed for reproducibility
        if not os.environ.get("SOVARA_SEED"):
            os.environ["SOVARA_SEED"] = str(random.randint(0, 2**31 - 1))

    def _apply_runtime_setup(self) -> None:
        """Apply runtime setup for execution environment."""
        set_parent_run_id(self.run_id)
        apply_all_monkey_patches()

    def _convert_file_to_module_name(self, script_path: str) -> str:
        abs_path = os.path.abspath(script_path)
        return os.path.splitext(os.path.basename(abs_path))[0]

    def _execute_user_code(self) -> int:
        """Execute the user's code directly in this process."""
        try:
            script_dir = os.path.dirname(os.path.abspath(self.script_path))
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)

            if self.is_module_execution:
                sys.argv = [self.script_path] + self.script_args
                runpy.run_module(self.script_path, run_name="__main__")
            else:
                module_name = self._convert_file_to_module_name(self.script_path)
                sys.argv = [self.script_path] + self.script_args
                runpy.run_module(module_name, run_name="__main__")
            return 0
        except SystemExit as e:
            return e.code if e.code is not None else 0
        except Exception:
            traceback.print_exc()
            return 1

    def _run_debug_mode(self) -> int:
        """Run in debug mode with persistent restart loop."""
        logger.info("[AgentRunner] Debug mode detected. Running with restart capability.")
        exit_code = 0
        first_run = True

        while not self.shutdown_flag:
            if first_run:
                self._apply_runtime_setup()
                first_run = False

            exit_code = self._execute_user_code()
            logger.info(f"[AgentRunner] Script completed with exit code {exit_code}. Waiting...")

            while not self.shutdown_flag and not self.restart_event.is_set():
                time.sleep(MESSAGE_POLL_INTERVAL)

            if self.shutdown_flag:
                break
            if self.restart_event.is_set():
                logger.info("[AgentRunner] Restart requested, rerunning script...")
                self.restart_event.clear()
                DB._occurrence_counters.clear()
                reset_current_run_timer()

        return exit_code

    def _run_normal_mode(self) -> int:
        """Run in normal mode (single execution)."""
        self._apply_runtime_setup()
        return self._execute_user_code()

    def run(self) -> None:
        """Main entry point."""
        try:
            self._setup_environment()
            ensure_server_running()

            # Set server URL for HTTP communication
            self.server_url = f"http://{HOST}:{PORT}"
            set_server_url(self.server_url)

            self._register_with_server()

            # Start SSE listener for server events (restart, shutdown)
            self.listener_thread = threading.Thread(
                target=self._listen_for_server_events, daemon=True
            )
            self.listener_thread.start()

            # Send restart command asynchronously
            def send_restart_command():
                try:
                    cmd = self._restart_command_future.result()
                    http_post("/runner/update-command", {
                        "run_id": self.run_id,
                        "command": cmd,
                    })
                except Exception as e:
                    _log_error("Failed to send restart command", e)

            threading.Thread(target=send_restart_command, daemon=True).start()

            if self._is_debugpy_session():
                exit_code = self._run_debug_mode()
            else:
                exit_code = self._run_normal_mode()

        finally:
            self._send_deregister(timeout=0.5 if self.shutdown_flag else None)
            clear_run_timer(self.run_id)
            self.shutdown_flag = True
            if self.listener_thread:
                self.listener_thread.join(timeout=2)

        sys.exit(exit_code)
