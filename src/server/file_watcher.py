"""
Git versioning process for code snapshots.

This module implements a background process that handles git versioning
of user code. When a new experiment is started, it commits the current
state of the project and returns a version string for display.
"""

import os
import time
import signal
import threading
import queue
import subprocess
import shutil
import traceback
from datetime import datetime
from typing import Optional
from ao.common.logger import create_file_logger
from ao.common.constants import (
    ORPHAN_POLL_INTERVAL,
    FILE_WATCHER_LOG,
    GIT_DIR,
)

logger = create_file_logger(FILE_WATCHER_LOG)


class FileWatcher:
    """
    Handles git versioning for code snapshots.

    This class runs as a background process and responds to version requests
    by committing the current project state and returning a version string.
    """

    def __init__(self, project_root: str = None, watch_queue=None, response_queue=None):
        """
        Initialize the file watcher.

        Args:
            project_root: Root directory of the project to version.
                         Falls back to cwd if not provided.
            watch_queue: multiprocessing.Queue for receiving messages from MainServer.
            response_queue: multiprocessing.Queue for sending messages back to MainServer.
        """
        self.pid = os.getpid()
        self._parent_pid = os.getppid()
        self._shutdown = False
        self.project_root = project_root or os.getcwd()
        self.watch_queue = watch_queue
        self.response_queue = response_queue
        # Git versioning state (lazy init)
        self._git_available: Optional[bool] = None
        self._git_initialized = False
        self._git_dir = os.path.abspath(GIT_DIR)
        logger.info(f"Started with project_root: {self.project_root}")
        self._setup_signal_handlers()

    # =========================================================================
    # Git Versioning
    # =========================================================================

    def _is_git_available(self) -> bool:
        """Check if git is installed on the system."""
        if self._git_available is None:
            self._git_available = shutil.which("git") is not None
            if not self._git_available:
                logger.warning("git not found in PATH, code versioning disabled")
        return self._git_available

    def _run_git(self, *args, check: bool = True) -> subprocess.CompletedProcess:
        """Run git command with GIT_DIR and GIT_WORK_TREE set."""
        env = os.environ.copy()
        env["GIT_DIR"] = self._git_dir
        env["GIT_WORK_TREE"] = self.project_root

        cmd = ["git"] + list(args)
        return subprocess.run(
            cmd,
            env=env,
            cwd=self.project_root,
            check=check,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def _format_version(self, dt: datetime) -> str:
        """Format datetime as 'Version Dec 12, 8:45' (24h format)."""
        return f"Version {dt.strftime('%b')} {dt.day}, {dt.hour}:{dt.strftime('%M')}"

    def _ensure_git_initialized(self) -> bool:
        """Ensure the git repository is initialized. Returns True on success."""
        if self._git_initialized:
            return True

        if not self._is_git_available():
            return False

        try:
            # Check if already initialized
            if os.path.exists(os.path.join(self._git_dir, "HEAD")):
                self._git_initialized = True
                return True

            # Create git directory
            os.makedirs(self._git_dir, exist_ok=True)

            # Initialize repository
            self._run_git("init")

            # Configure user for commits (required by git)
            self._run_git("config", "user.name", "AO Code Versioner")
            self._run_git("config", "user.email", "ao@localhost")

            logger.info(f"Initialized git repository at {self._git_dir}")
            self._git_initialized = True
            return True

        except subprocess.SubprocessError as e:
            logger.error(f"Failed to initialize git repository: {e}")
            return False
        except OSError as e:
            logger.error(f"Failed to create git directory: {e}")
            return False

    def _commit_and_get_version(self) -> Optional[str]:
        """
        Commit all files in project root and return version string.

        Uses `git add .` to stage all files in the project root.

        Returns:
            Human-readable version string like "Version Dec 12, 8:45", or None if unavailable.
        """
        if not self._ensure_git_initialized():
            return None

        try:
            # Stage all files in project root
            self._run_git("add", ".")

            # Check if there are staged changes
            result = self._run_git("diff", "--cached", "--quiet", check=False)

            if result.returncode == 0:
                # No changes - return timestamp of current HEAD if it exists
                try:
                    result = self._run_git("log", "-1", "--format=%cI", "HEAD")
                    timestamp_str = result.stdout.strip()
                    dt = datetime.fromisoformat(timestamp_str)
                    return self._format_version(dt)
                except subprocess.SubprocessError:
                    # No commits yet and no changes
                    return None

            # There are changes - commit them
            now = datetime.now()
            commit_message = now.isoformat(timespec="seconds")
            self._run_git("commit", "-m", commit_message)

            version_str = self._format_version(now)
            logger.info(f"Created git commit: {version_str}")
            return version_str

        except subprocess.SubprocessError as e:
            stderr = getattr(e, "stderr", None)
            logger.error(f"Git operation failed: {e}, stderr: {stderr}")
            return None
        except subprocess.TimeoutExpired:
            logger.error("Git operation timed out")
            return None

    def _handle_version_request(self, session_id: str) -> None:
        """Handle a request_version message: commit files and return version_date."""
        version_date = self._commit_and_get_version()
        if self.response_queue:
            self.response_queue.put(
                {
                    "type": "version_result",
                    "session_id": session_id,
                    "version_date": version_date,
                }
            )

    # =========================================================================
    # Process Management
    # =========================================================================

    def _setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)

    def _handle_shutdown_signal(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self._shutdown = True

    def _is_parent_alive(self) -> bool:
        """Check if parent process is alive (PPID becomes 1 when parent dies)."""
        current_ppid = os.getppid()
        return current_ppid == self._parent_pid and current_ppid != 1

    def _start_parent_monitor(self) -> None:
        """Start a daemon thread that monitors if the parent process is still alive."""

        def monitor_parent():
            while not self._shutdown:
                if not self._is_parent_alive():
                    logger.info("Parent process died, shutting down...")
                    self._shutdown = True
                    return
                time.sleep(ORPHAN_POLL_INTERVAL)

        thread = threading.Thread(target=monitor_parent, daemon=True)
        thread.start()

    def _process_queue(self):
        """Process messages from MainServer (version requests only)."""
        if not self.watch_queue:
            return

        while True:
            try:
                msg = self.watch_queue.get_nowait()

                # Handle dict messages (structured commands)
                if isinstance(msg, dict):
                    msg_type = msg.get("type")
                    if msg_type == "request_version":
                        self._handle_version_request(msg.get("session_id"))
                    else:
                        logger.warning(f"Unknown message type: {msg_type}")
                else:
                    # Ignore string messages (no longer handling file paths)
                    pass
            except queue.Empty:
                break

    def run(self):
        """Main loop that processes version requests."""
        # Start parent monitor thread (detects orphaned process)
        self._start_parent_monitor()

        # Main loop - just process queue messages
        try:
            while not self._shutdown:
                self._process_queue()
                time.sleep(0.5)  # Check queue every 500ms
        except Exception:
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
        finally:
            logger.info(f"File watcher process {self.pid} exiting")


def run_file_watcher_process(project_root: str = None, watch_queue=None, response_queue=None):
    """
    Entry point for the file watcher process.

    This function is called when the file watcher runs as a separate process.
    It creates a FileWatcher instance and starts the monitoring loop.

    Args:
        project_root: Root directory of the project (from VS Code workspace)
        watch_queue: multiprocessing.Queue for receiving messages from MainServer
        response_queue: multiprocessing.Queue for sending messages back to MainServer
    """
    watcher = FileWatcher(project_root, watch_queue, response_queue)
    watcher.run()
