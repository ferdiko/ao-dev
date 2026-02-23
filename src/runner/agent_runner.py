#!/usr/bin/env python3

import sys
import os
import socket
import json
import shlex
import random
import threading
import traceback
import queue
import time
import psutil
import signal
import runpy

from typing import Optional, List

from ao.common.logger import logger
from ao.common.constants import (
    HOST,
    PORT,
    CONNECTION_TIMEOUT,
    SERVER_START_TIMEOUT,
    MESSAGE_POLL_INTERVAL,
)
from ao.cli.ao_server import launch_daemon_server
from ao.runner.context_manager import set_parent_session_id, set_server_connection
from ao.runner.monkey_patching.apply_monkey_patches import apply_all_monkey_patches
from ao.server.database_manager import DB


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
            # lsof returns PIDs, one per line - take the first one
            pid_str = result.stdout.strip().split("\n")[0]
            return int(pid_str)
    except Exception as e:
        logger.debug(f"Could not check port {port} with lsof: {e}")
    return None


def _kill_zombie_server(pid: int) -> bool:
    """
    Kill a zombie server process gracefully.
    Returns True if the process was killed or doesn't exist.
    """
    try:
        # First try SIGTERM (graceful shutdown)
        os.kill(pid, signal.SIGTERM)
        logger.info(f"Sent SIGTERM to zombie server process {pid}")

        # Wait up to 3 seconds for it to die
        for _ in range(6):
            time.sleep(0.5)
            try:
                # Check if process still exists (os.kill with signal 0)
                os.kill(pid, 0)
            except OSError:
                # Process is gone
                logger.info(f"Zombie server process {pid} terminated")
                return True

        # Still alive, try SIGKILL
        logger.warning(f"Process {pid} didn't respond to SIGTERM, sending SIGKILL")
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
        return True

    except OSError as e:
        if e.errno == 3:  # No such process
            return True
        logger.warning(f"Could not kill process {pid}: {e}")
        return False


def ensure_server_running() -> None:
    """Ensure the develop server is running, start it if necessary."""
    # First, try to connect to see if server is healthy
    try:
        socket.create_connection((HOST, PORT), timeout=SERVER_START_TIMEOUT).close()
        logger.debug(f"Server already running on {HOST}:{PORT}")
        return
    except ConnectionRefusedError:
        # Port is free, no process listening - safe to launch
        logger.info(f"No server on {HOST}:{PORT}, starting new one...")
    except socket.timeout:
        # Connection timed out - might be a zombie process
        logger.warning(f"Server on {HOST}:{PORT} not responding, checking for zombie process...")
        zombie_pid = _find_process_on_port(PORT)
        if zombie_pid:
            logger.warning(f"Found unresponsive server process {zombie_pid}, killing it...")
            if _kill_zombie_server(zombie_pid):
                # Wait a moment for port to be released
                time.sleep(1)
            else:
                logger.error(f"Could not kill zombie process {zombie_pid}")
    except Exception as e:
        # Other connection error - log and try to start anyway
        logger.info(f"Connection to {HOST}:{PORT} failed ({e}), attempting to start server...")

    # Launch new daemon
    launch_daemon_server()
    logger.debug(f"Daemon launched, waiting for startup...")

    # Poll for server availability
    max_wait = 15
    poll_interval = 0.5
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval
        try:
            socket.create_connection((HOST, PORT), timeout=1).close()
            logger.info(f"Server started successfully after {elapsed:.1f}s")
            return
        except Exception:
            if elapsed % 5 < poll_interval:
                logger.debug(f"Waiting for server... ({elapsed:.1f}s elapsed)")

    # Final attempt with full timeout
    logger.warning(f"Server not ready after {max_wait}s, making final connection attempt...")
    socket.create_connection((HOST, PORT), timeout=CONNECTION_TIMEOUT).close()
    logger.info("Server started successfully (final attempt)")


class AgentRunner:
    """Unified agent runner that combines orchestration and execution in a single process."""

    def __init__(
        self,
        script_path: str,
        script_args: List[str],
        is_module_execution: bool,
        sample_id: Optional[str] = None,
        user_id: Optional[str] = None,
        run_name: Optional[str] = None,
    ):
        self.script_path = script_path
        self.script_args = script_args
        self.is_module_execution = is_module_execution
        self.sample_id = sample_id
        self.user_id = user_id
        self.run_name = run_name

        # State management
        self.shutdown_flag = False
        self.restart_event = threading.Event()
        self.process_id = os.getpid()

        # Server communication
        self.session_id: Optional[str] = None
        self.server_conn: Optional[socket.socket] = None

        # Threading for server messages
        self.listener_thread: Optional[threading.Thread] = None

        # Queue for synchronous request-response messages (e.g., add_subrun responses)
        # The listener thread routes non-control messages here for send_to_server_and_receive
        self.response_queue: queue.Queue = queue.Queue()

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Start computing restart command in background (it's slow due to psutil)
        from concurrent.futures import ThreadPoolExecutor

        self._executor = ThreadPoolExecutor(max_workers=1)
        self._restart_command_future = self._executor.submit(self._generate_restart_command)

    def _send_message(self, msg_type: str, **kwargs) -> None:
        """Send a message to the develop server."""
        if not self.server_conn:
            return
        message = {"type": msg_type, "role": "agent-runner", **kwargs}
        if self.session_id:
            message["session_id"] = self.session_id
        try:
            self.server_conn.sendall((json.dumps(message) + "\n").encode("utf-8"))
        except Exception as e:
            _log_error("Failed to send message to server", e)

    def send_deregister(self) -> None:
        """Send deregistration message to the develop server."""
        self._send_message("deregister")

    def _signal_handler(self, signum, frame) -> None:
        """Handle termination signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.send_deregister()
        if self.server_conn:
            try:
                self.server_conn.close()
            except Exception as e:
                _log_error("Error closing server connection", e)
        sys.exit(0)

    def _listen_for_server_messages(self, sock: socket.socket) -> None:
        """Background thread: listen for 'restart' or 'shutdown' messages from the server."""
        try:
            buffer = b""
            while not self.shutdown_flag:
                try:
                    import select

                    rlist, _, _ = select.select([sock], [], [], 1.0)
                    if rlist:
                        data = sock.recv(4096)
                        logger.info(
                            f"[AgentRunner] Listener received raw data: {data[:200] if data else 'empty'}"
                        )
                        if not data:
                            break
                        buffer += data
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            logger.info(f"[AgentRunner] Listener parsed line: {line[:200]}")
                            try:
                                msg = json.loads(line.decode("utf-8").strip())
                                self._handle_server_message(msg)
                            except json.JSONDecodeError as e:
                                logger.error(
                                    f"[AgentRunner] Listener JSON decode error: {e}, line: {line}"
                                )
                                continue
                except Exception as e:
                    _log_error("Error in message listener", e)
                    break
        except Exception as e:
            _log_error("Error in listener thread", e)
        finally:
            try:
                sock.close()
            except Exception as e:
                _log_error("Error closing socket", e)

    def _handle_server_message(self, msg: dict) -> None:
        """Handle incoming server messages.

        Control messages (restart, shutdown) are handled directly.
        Response messages are routed by request_id to the correct waiting thread.
        """
        msg_type = msg.get("type")
        if msg_type == "restart":
            logger.info(f"[AgentRunner] Received restart message: {msg}")
            self.restart_event.set()
        elif msg_type == "shutdown":
            logger.info(f"[AgentRunner] Received shutdown message: {msg}")
            self.shutdown_flag = True
        else:
            from ao.common.utils import route_response
            if not route_response(msg):
                # No matching request_id — fall back to legacy queue
                logger.debug(f"[AgentRunner] Unmatched response to queue: {msg}")
                self.response_queue.put(msg)

    def _is_debugpy_session(self) -> bool:
        """Detect if we're running under debugpy (VSCode debugging)."""
        if os.environ.get("AO_NO_DEBUG_MODE", False):
            return False

        # Only import debugpy if it's already loaded (by VS Code)
        if "debugpy" not in sys.modules:
            return False

        try:
            import debugpy

            return debugpy.is_client_connected() or hasattr(debugpy, "_client")
        except (ImportError, AttributeError):
            return True  # debugpy in sys.modules but can't check - assume debugging

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
            # Always include python executable to ensure command is runnable
            # sys.argv[0] may be a .py file path which isn't directly executable
            return f"{python_executable} {original_command}"
        parent_cmdline = self._get_parent_cmdline()

        if not parent_cmdline:
            return f"/usr/bin/env {python_executable} {original_command}"

        cmdline_str = " ".join(shlex.quote(arg) for arg in parent_cmdline)

        # Pattern 1: VSCode launcher - debugpy/launcher PORT -- args
        if "launcher" in cmdline_str and "--" in parent_cmdline:
            dash_index = parent_cmdline.index("--")
            original_args = " ".join(shlex.quote(arg) for arg in parent_cmdline[dash_index + 1 :])
            return f"/usr/bin/env {python_executable} {original_args}"

        # Pattern 2: Direct debugpy module - python -m debugpy [options] -m module/script
        if "-m" in parent_cmdline and "debugpy" in parent_cmdline:
            if self.is_module_execution:
                target_args = f"-m {self.script_path} {' '.join(shlex.quote(arg) for arg in self.script_args)}"
            else:
                target_args = f"{shlex.quote(self.script_path)} {' '.join(shlex.quote(arg) for arg in self.script_args)}"
            return f"{python_executable} {target_args}"

        # Fallback: basic command
        if self.is_module_execution:
            target_args = (
                f"-m {self.script_path} {' '.join(shlex.quote(arg) for arg in self.script_args)}"
            )
        else:
            target_args = f"{shlex.quote(self.script_path)} {' '.join(shlex.quote(arg) for arg in self.script_args)}"

        return f"{python_executable} {target_args}"

    def _connect_to_server(self) -> None:
        """Connect to the develop server and perform handshake."""
        logger.info(f"[AgentRunner] Connecting to server at {HOST}:{PORT}...")
        try:
            self.server_conn = socket.create_connection((HOST, PORT), timeout=CONNECTION_TIMEOUT)
            logger.info(f"[AgentRunner] Connected to server")
        except Exception as e:
            logger.error(f"Cannot connect to develop server: {e}")
            sys.exit(1)

        # Build handshake without command (sent async later)
        handshake = {
            "type": "hello",
            "role": "agent-runner",
            "name": self.run_name,
            "cwd": os.getcwd(),
            "environment": dict(os.environ),
            "process_id": self.process_id,
            "prev_session_id": os.getenv("AO_SESSION_ID"),
        }

        if self.user_id is not None:
            handshake["user_id"] = str(self.user_id)

        try:
            logger.info(f"[AgentRunner] Sending handshake...")
            self.server_conn.sendall((json.dumps(handshake) + "\n").encode("utf-8"))
            logger.info(f"[AgentRunner] Handshake sent, waiting for response...")
            file_obj = self.server_conn.makefile(mode="r")
            session_line = file_obj.readline()
            logger.info(
                f"[AgentRunner] Received response: {session_line[:100] if session_line else 'empty'}"
            )
            if session_line:
                session_msg = json.loads(session_line.strip())
                self.session_id = session_msg.get("session_id")
                database_mode = session_msg.get("database_mode")
                if database_mode:
                    DB.switch_mode(database_mode)
                    logger.debug(f"Using database mode: {database_mode}")
                logger.info(f"Registered with session_id: {self.session_id}")

                # Write session info to file for ao-tool IPC
                session_file = os.environ.get("AO_SESSION_FILE")
                if session_file:
                    try:
                        with open(session_file, "w") as f:
                            json.dump({"session_id": self.session_id, "pid": self.process_id}, f)
                    except Exception as e:
                        logger.warning(f"Failed to write session file: {e}")
        except Exception as e:
            _log_error("Server communication failed", e)
            raise

    def _setup_environment(self) -> None:
        """Set up the execution environment for the agent runner."""
        # Set random seed for reproducibility
        if not os.environ.get("AO_SEED"):
            os.environ["AO_SEED"] = str(random.randint(0, 2**31 - 1))

    def _apply_runtime_setup(self) -> None:
        """Apply runtime setup for the agent runner execution environment."""
        # Set up context manager with server connection and response queue
        set_parent_session_id(self.session_id)
        set_server_connection(self.server_conn, self.response_queue)

        # Apply monkey patches (includes random seeding - numpy/torch are lazy)
        apply_all_monkey_patches()

    def _convert_file_to_module_name(self, script_path: str) -> str:
        """Convert a file path to a module name (just the basename without .py)."""
        abs_path = os.path.abspath(script_path)
        return os.path.splitext(os.path.basename(abs_path))[0]

    def _execute_user_code(self) -> int:
        """Execute the user's code directly in this process.

        Returns:
            Exit code from the user's script (0 for success, non-zero for error)
        """
        try:
            # Add script's directory to sys.path (mimics Python's behavior)
            script_dir = os.path.dirname(os.path.abspath(self.script_path))
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)

            # Run user program
            if self.is_module_execution:
                # -m flag: user provides module name directly
                sys.argv = [self.script_path] + self.script_args
                runpy.run_module(self.script_path, run_name="__main__")
            else:
                # Script path: convert to module name (basename) and run
                module_name = self._convert_file_to_module_name(self.script_path)
                sys.argv = [self.script_path] + self.script_args
                runpy.run_module(module_name, run_name="__main__")
            return 0
        except SystemExit as e:
            return e.code if e.code is not None else 0
        except Exception as e:
            # Print traceback to stderr so user sees it (regardless of logger level)
            traceback.print_exc()
            return 1

    def _run_debug_mode(self) -> int:
        """Run the script in debug mode with persistent restart loop.

        In debug mode, after the script completes, we wait for either a restart
        signal (from the UI) or a shutdown signal before exiting. This allows
        the user to re-run the script without restarting the debug session.

        Returns:
            Exit code from the last script execution
        """
        logger.info("[AgentRunner] Debug mode detected. Running with restart capability.")
        exit_code = 0
        first_run = True

        while not self.shutdown_flag:
            logger.info("[AgentRunner] Running script...")

            # Only apply runtime setup (monkey patches, etc.) on first run
            # to avoid double-patching issues on restart
            if first_run:
                self._apply_runtime_setup()
                first_run = False

            exit_code = self._execute_user_code()

            logger.info(
                f"[AgentRunner] Script completed with exit code {exit_code}. "
                "Waiting for restart or shutdown..."
            )

            # Wait for either restart or shutdown signal
            while not self.shutdown_flag and not self.restart_event.is_set():
                time.sleep(MESSAGE_POLL_INTERVAL)

            if self.shutdown_flag:
                logger.info("[AgentRunner] Shutdown requested, exiting debug mode.")
                break

            if self.restart_event.is_set():
                logger.info("[AgentRunner] Restart requested, rerunning script...")
                self.restart_event.clear()
                continue

        return exit_code

    def _run_normal_mode(self) -> int:
        """Run the script in normal mode (single execution).

        Returns:
            Exit code from the script execution
        """
        self._apply_runtime_setup()
        return self._execute_user_code()

    def run(self) -> None:
        """Main entry point to run the unified agent runner."""
        try:
            self._setup_environment()
            ensure_server_running()
            self._connect_to_server()

            self.listener_thread = threading.Thread(
                target=self._listen_for_server_messages, args=(self.server_conn,), daemon=True
            )
            self.listener_thread.start()

            # Send restart command asynchronously (it's slow to compute, only needed for UI restart)
            def send_restart_command():
                try:
                    cmd = self._restart_command_future.result()
                    self._send_message("update_command", command=cmd)
                except Exception as e:
                    _log_error("Failed to send restart command", e)

            threading.Thread(target=send_restart_command, daemon=True).start()

            # Use debug mode if running under debugpy, otherwise normal mode
            if self._is_debugpy_session():
                exit_code = self._run_debug_mode()
            else:
                exit_code = self._run_normal_mode()

        finally:
            self.send_deregister()
            if self.server_conn:
                try:
                    self.server_conn.close()
                except Exception as e:
                    _log_error("Error closing server connection in cleanup", e)

            if self.listener_thread:
                self.listener_thread.join(timeout=2)

        sys.exit(exit_code)
