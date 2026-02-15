import socket
import os
import json
import threading
import subprocess
import time
import uuid
import shlex
import signal
import shutil
from datetime import datetime
from typing import Optional

from ao.common.logger import create_file_logger
from ao.common.constants import (
    AO_CONFIG,
    MAIN_SERVER_LOG,
    HOST,
    PORT,
    SERVER_INACTIVITY_TIMEOUT,
    PLAYBOOK_SERVER_URL,
    PLAYBOOK_API_KEY,
    GIT_DIR,
)
from ao.server.database_manager import DB
from ao.server.handlers import (
    send_json,
    # UI handlers
    handle_restart_message,
    handle_edit_input,
    handle_edit_output,
    handle_update_node,
    handle_update_run_name,
    handle_update_result,
    handle_update_notes,
    handle_get_graph,
    handle_erase,
    handle_get_all_experiments,
    # Runner handlers
    handle_add_node,
    handle_add_subrun,
    handle_deregister_message,
    handle_update_command,
    handle_log,
    # Lesson handlers
    handle_get_lessons,
    handle_add_lesson,
    handle_update_lesson,
    handle_delete_lesson,
    handle_get_lesson,
)

logger = create_file_logger(MAIN_SERVER_LOG)


class Session:
    """Represents a running develop process and its associated UI clients."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.shim_conn: Optional[socket.socket] = None
        self.status = "running"
        self.lock = threading.Lock()


class MainServer:
    """Manages the development server for LLM call visualization."""

    def __init__(self):
        logger.info("__init__ starting...")
        self.server_sock = None
        self.lock = threading.Lock()
        self.conn_info = {}  # conn -> {role, session_id}
        self.session_graphs = {}  # session_id -> graph_data
        self.ui_connections = set()
        self.sessions = {}  # session_id -> Session (only for agent runner connections)
        self.rerun_sessions = set()  # Track sessions being rerun to avoid clearing llm_calls
        self._last_activity_time = time.time()  # Track last message received for inactivity timeout
        self._project_root = None  # Workspace root from VS Code UI
        # Git versioning state
        self._git_available: Optional[bool] = None
        self._git_initialized = False
        self._git_dir = os.path.abspath(GIT_DIR)
        # Git versioning executor (runs commits in background)
        from concurrent.futures import ThreadPoolExecutor

        self._git_executor = ThreadPoolExecutor(max_workers=1)

    # ============================================================
    # Git Versioning
    # ============================================================

    def _is_git_available(self) -> bool:
        """Check if git is installed on the system."""
        if self._git_available is None:
            self._git_available = shutil.which("git") is not None
            if not self._git_available:
                logger.warning("git not found in PATH, code versioning disabled")
        return self._git_available

    def _run_git(self, *args, check: bool = True) -> subprocess.CompletedProcess:
        """Run git command with GIT_DIR and GIT_WORK_TREE set."""
        project_root = self._project_root or os.getcwd()
        env = os.environ.copy()
        env["GIT_DIR"] = self._git_dir
        env["GIT_WORK_TREE"] = project_root

        cmd = ["git"] + list(args)
        return subprocess.run(
            cmd,
            env=env,
            cwd=project_root,
            check=check,
            capture_output=True,
            text=True,
            timeout=30,
        )

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
                    return f"Version {dt.strftime('%b')} {dt.day}, {dt.hour}:{dt.strftime('%M')}"
                except subprocess.SubprocessError:
                    # No commits yet and no changes
                    return None

            # There are changes - commit them
            now = datetime.now()
            commit_message = now.isoformat(timespec="seconds")
            self._run_git("commit", "-m", commit_message)

            version_str = f"Version {now.strftime('%b')} {now.day}, {now.hour}:{now.strftime('%M')}"
            logger.info(f"Created git commit: {version_str}")
            return version_str

        except subprocess.SubprocessError as e:
            stderr = getattr(e, "stderr", None)
            logger.error(f"Git operation failed: {e}, stderr: {stderr}")
            return None
        except subprocess.TimeoutExpired:
            logger.error("Git operation timed out")
            return None

    def _do_git_version(self, session_id: str) -> None:
        """Background thread: commit files and update experiment version_date."""
        version_date = self._commit_and_get_version()
        if version_date:
            DB.update_experiment_version_date(session_id, version_date)
        self.broadcast_experiment_list_to_uis()

    # ============================================================
    # Inactivity Monitor
    # ============================================================

    def _start_inactivity_monitor(self) -> None:
        """Start a daemon thread that shuts down the server after inactivity timeout."""

        def monitor_inactivity():
            while True:
                time.sleep(60)  # Check every minute
                elapsed = time.time() - self._last_activity_time
                if elapsed >= SERVER_INACTIVITY_TIMEOUT:
                    logger.info(f"No activity for {elapsed:.0f}s, shutting down...")
                    self.handle_shutdown()
                    return

        thread = threading.Thread(target=monitor_inactivity, daemon=True)
        thread.start()

    # ============================================================
    # Broadcasting Utils
    # ============================================================

    def broadcast_to_all_uis(self, msg: dict) -> None:
        """Broadcast a message to all UI connections."""
        msg_type = msg.get("type", "unknown")
        logger.debug(
            f"broadcast_to_all_uis: type={msg_type}, num_ui_connections={len(self.ui_connections)}"
        )
        for ui_conn in list(self.ui_connections):
            try:
                send_json(ui_conn, msg)
            except Exception as e:
                logger.error(f"Error broadcasting to UI: {e}")
                self.ui_connections.discard(ui_conn)

    def broadcast_graph_update(self, session_id: str) -> None:
        """Broadcast current graph state for a session to all UIs."""
        if session_id in self.session_graphs:
            graph = self.session_graphs[session_id]
            logger.info(
                f"broadcast_graph_update: session={session_id}, nodes={len(graph.get('nodes', []))}, edges={[e['id'] for e in graph.get('edges', [])]}"
            )
            self.broadcast_to_all_uis(
                {
                    "type": "graph_update",
                    "session_id": session_id,
                    "payload": graph,
                }
            )

    def broadcast_experiment_list_to_uis(self, conn=None) -> None:
        """Only broadcast to one UI (conn) or, if conn is None, to all."""

        def build_and_send(target_conn, db_rows):
            session_map = {session.session_id: session for session in self.sessions.values()}
            experiment_list = []
            for row in db_rows:
                session_id = row["session_id"]
                session = session_map.get(session_id)

                # Get status from in-memory session, or default to "finished"
                status = session.status if session else "finished"

                # Get data from DB entries.
                timestamp = row["timestamp"]
                # Format timestamp as ISO string for frontend parsing
                if hasattr(timestamp, "isoformat"):
                    timestamp = timestamp.isoformat()
                elif hasattr(timestamp, "strftime"):
                    timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    # If it's already a string, ensure it's in a parseable format
                    try:
                        from datetime import datetime

                        dt = datetime.strptime(str(timestamp), "%Y-%m-%d %H:%M:%S")
                        timestamp = dt.isoformat()
                    except:
                        # If parsing fails, use as-is
                        pass

                run_name = row["name"]
                success = row["success"]
                notes = row["notes"]
                log = row["log"]
                version_date = row["version_date"]

                # Parse color_preview from database
                color_preview = []
                if row["color_preview"]:
                    try:
                        color_preview = json.loads(row["color_preview"])
                    except:
                        color_preview = []

                experiment_list.append(
                    {
                        "session_id": session_id,
                        "status": status,
                        "timestamp": timestamp,
                        "color_preview": color_preview,
                        "version_date": version_date,
                        "run_name": run_name,
                        "result": success,
                        "notes": notes,
                        "log": log,
                    }
                )

            msg = {"type": "experiment_list", "experiments": experiment_list}
            try:
                send_json(target_conn, msg)
            except Exception as e:
                logger.error(f"Error sending experiment list to UI: {e}")

        # Auth disabled - get all experiments without user filtering
        db_experiments = DB.get_all_experiments_sorted()
        if conn:
            build_and_send(conn, db_experiments)
            return

        # Broadcast to all UIs
        for ui_conn in list(self.ui_connections):
            build_and_send(ui_conn, db_experiments)

    def print_graph(self, session_id):
        # Debug utility.
        print("\n--------------------------------")
        # Print list of all sessions and their status.
        for session_id, session in self.sessions.items():
            print(f"Session {session_id}: {session.status}")

        # Print graph for the given session_id.
        print(f"\nGraph for session_id: {session_id}")
        graph = self.session_graphs.get(session_id)
        if graph:
            print(json.dumps(graph, indent=4))
        else:
            print(f"No graph found for session_id: {session_id}")
        print("--------------------------------\n")

    # ============================================================
    # Helper methods
    # ============================================================

    def _clear_session_ui(self, session_id: str) -> None:
        """Clear UI state for a session (graphs and color previews)."""
        # Clear graph in both memory and database atomically to prevent stale data
        empty_graph = {"nodes": [], "edges": []}
        self.session_graphs[session_id] = empty_graph
        DB.update_graph_topology(session_id, empty_graph)

        # Reset color previews in both memory and database
        DB.update_color_preview(session_id, [])
        self.broadcast_to_all_uis(
            {"type": "color_preview_update", "session_id": session_id, "color_preview": []}
        )

        # Broadcast empty graph to all UIs
        self.broadcast_to_all_uis(
            {
                "type": "graph_update",
                "session_id": session_id,
                "payload": empty_graph,
            }
        )

    def _spawn_session_process(self, session_id: str, child_session_id: str) -> None:
        """Spawn a new session process with the original command and environment."""
        try:
            cwd, command, environment = DB.get_exec_command(session_id)
            logger.debug(
                f"Rerunning finished session {session_id} with cwd={cwd} and command={command}"
            )

            # Mark this session as being rerun to avoid clearing llm_calls
            self.rerun_sessions.add(child_session_id)

            # Set up environment
            env = os.environ.copy()
            env["AO_SESSION_ID"] = session_id
            env.update(environment)
            logger.debug(
                f"Restored {len(environment)} environment variables for session {session_id}"
            )

            # Spawn the process
            args = shlex.split(command)
            subprocess.Popen(args, cwd=cwd, env=env, close_fds=True, start_new_session=True)

            # Update session status and timestamp
            session = self.sessions.get(child_session_id)
            if session:
                session.status = "running"
                DB.update_timestamp(child_session_id, datetime.now())
                self.broadcast_experiment_list_to_uis()

        except Exception as e:
            logger.error(f"Failed to rerun finished session: {e}")

    def load_finished_runs(self):
        """Load finished runs from database into sessions dict."""
        try:
            rows = DB.get_finished_runs()
            for row in rows:
                session_id = row["session_id"]
                session = self.sessions.get(session_id)
                if not session:
                    session = Session(session_id)
                    session.status = "finished"
                    self.sessions[session_id] = session
        except Exception as e:
            logger.warning(f"Failed to load finished runs from database: {e}")

    # ============================================================
    # Admin Handlers (remain in main_server.py)
    # ============================================================

    def handle_shutdown(self) -> None:
        """Handle shutdown command by closing all connections."""
        logger.info("Shutdown command received. Closing all connections.")
        # Shutdown git executor
        self._git_executor.shutdown(wait=False)
        # Close all client sockets
        for s in list(self.conn_info.keys()):
            try:
                s.close()
            except Exception as e:
                logger.error(f"Error closing socket: {e}")
        os._exit(0)

    def handle_clear(self):
        """Clear all experiments and graphs."""
        DB.clear_db()
        self.session_graphs.clear()
        self.sessions.clear()
        self.broadcast_experiment_list_to_uis()
        self.broadcast_to_all_uis(
            {"type": "graph_update", "session_id": None, "payload": {"nodes": [], "edges": []}}
        )

    def handle_set_database_mode(self, msg: dict):
        """Handle database mode switching from UI dropdown."""
        mode = msg.get("mode")  # "local" or "remote"
        if mode not in ["local", "remote"]:
            logger.error(f"Invalid database mode: {mode}")
            return

        try:
            current_mode = DB.get_current_mode()
            if current_mode != mode:
                DB.switch_mode(mode)

                # Broadcast the mode change to all UIs so they can update their UI controls
                self.broadcast_to_all_uis({"type": "database_mode_changed", "database_mode": mode})

                # Refresh experiment list with new database - UI will see different data
                self.broadcast_experiment_list_to_uis()

        except Exception as e:
            logger.error(f"Failed to switch database mode: {e}")

    # ============================================================
    # Message routing logic.
    # ============================================================

    def process_message(self, msg: dict, conn: socket.socket) -> None:
        self._last_activity_time = time.time()  # Reset inactivity timer
        msg_type = msg.get("type")

        # Admin handlers (stay in main_server.py)
        if msg_type == "shutdown":
            self.handle_shutdown()
        elif msg_type == "clear":
            self.handle_clear()
        elif msg_type == "set_database_mode":
            self.handle_set_database_mode(msg)

        # UI handlers
        elif msg_type == "restart":
            handle_restart_message(self, msg)
        elif msg_type == "edit_input":
            handle_edit_input(self, msg)
        elif msg_type == "edit_output":
            handle_edit_output(self, msg)
        elif msg_type == "update_node":
            handle_update_node(self, msg)
        elif msg_type == "update_run_name":
            handle_update_run_name(self, msg)
        elif msg_type == "update_result":
            handle_update_result(self, msg)
        elif msg_type == "update_notes":
            handle_update_notes(self, msg)
        elif msg_type == "get_graph":
            handle_get_graph(self, msg, conn)
        elif msg_type == "erase":
            handle_erase(self, msg)
        elif msg_type == "get_all_experiments":
            handle_get_all_experiments(self, conn)

        # Runner handlers
        elif msg_type == "add_node":
            handle_add_node(self, msg)
        elif msg_type == "add_subrun":
            handle_add_subrun(self, msg, conn)
        elif msg_type == "deregister":
            handle_deregister_message(self, msg)
        elif msg_type == "update_command":
            handle_update_command(self, msg)
        elif msg_type == "log":
            handle_log(self, msg)

        # Lesson handlers
        elif msg_type == "get_lessons":
            handle_get_lessons(self, conn)
        elif msg_type == "add_lesson":
            handle_add_lesson(self, msg, conn)
        elif msg_type == "update_lesson":
            handle_update_lesson(self, msg, conn)
        elif msg_type == "delete_lesson":
            handle_delete_lesson(self, msg, conn)
        elif msg_type == "get_lesson":
            handle_get_lesson(self, msg, conn)

        else:
            logger.error(f"Unknown message type. Message:\n{msg}")

    def handle_client(self, conn: socket.socket) -> None:
        """Handle a new client connection in a separate thread."""
        file_obj = conn.makefile(mode="r")
        session: Optional[Session] = None
        role = None
        try:
            # Expect handshake first
            handshake_line = file_obj.readline()
            if not handshake_line:
                return
            handshake = json.loads(handshake_line.strip())
            self._last_activity_time = time.time()  # Reset inactivity timer on new connection
            role = handshake.get("role")
            session_id = None
            # Only assign session_id for agent-runner.
            if role == "agent-runner":
                # If rerun, use previous session_id. Else, assign new one.
                prev_session_id = handshake.get("prev_session_id")
                if prev_session_id:
                    session_id = prev_session_id
                else:
                    session_id = str(uuid.uuid4())
                    # Insert new experiment into DB.
                    cwd = handshake.get("cwd")
                    command = handshake.get("command")
                    environment = handshake.get("environment")
                    timestamp = datetime.now()
                    name = handshake.get("name")
                    if not name:
                        run_index = DB.get_next_run_index()
                        name = f"Run {run_index}"
                    # Create experiment with version_date=None, request async versioning
                    DB.add_experiment(
                        session_id,
                        name,
                        timestamp,
                        cwd,
                        command,
                        environment,
                        None,
                        None,  # user_id disabled
                        None,  # version_date will be set async
                    )
                    # Request async git versioning
                    self._git_executor.submit(self._do_git_version, session_id)
                # Insert session if not present.
                with self.lock:
                    if session_id not in self.sessions:
                        self.sessions[session_id] = Session(session_id)
                    session = self.sessions[session_id]
                with session.lock:
                    session.shim_conn = conn
                session.status = "running"
                self.broadcast_experiment_list_to_uis()
                self.conn_info[conn] = {"role": role, "session_id": session_id}
                send_json(
                    conn,
                    {
                        "type": "session_id",
                        "session_id": session_id,
                        "database_mode": DB.get_current_mode(),
                    },
                )

            elif role == "ui":
                # Always reload finished runs from the DB before sending experiment list
                self.load_finished_runs()
                self.ui_connections.add(conn)

                # Extract workspace_root from VS Code for git versioning
                workspace_root = handshake.get("workspace_root")
                if workspace_root and workspace_root != self._project_root:
                    logger.info(f"Setting workspace root to: {workspace_root}")
                    self._project_root = workspace_root

                # Send session_id and config_path to this UI connection (None for UI)
                self.conn_info[conn] = {"role": role, "session_id": None}
                send_json(
                    conn,
                    {
                        "type": "session_id",
                        "session_id": None,
                        "config_path": AO_CONFIG,
                        "database_mode": DB.get_current_mode(),
                        "playbook_url": PLAYBOOK_SERVER_URL,
                        "playbook_api_key": PLAYBOOK_API_KEY,
                    },
                )
                # Experiment list will be sent when UI explicitly requests it

            # Main message loop
            try:
                for line in file_obj:
                    try:
                        msg = json.loads(line.strip())
                    except Exception as e:
                        logger.error(f"Error parsing JSON: {e}")
                        continue

                    msg_type = msg.get("type", "unknown")
                    logger.debug(f"Received message type: {msg_type}")

                    if "session_id" not in msg:
                        msg["session_id"] = session_id

                    self.process_message(msg, conn)

            except (ConnectionResetError, OSError):
                pass  # Expected when connections close
        finally:
            # Clean up connection
            info = self.conn_info.pop(conn, None)
            # Only mark session finished for agent-runner disconnects
            if info and role == "agent-runner":
                session = self.sessions.get(info["session_id"])
                if session:
                    with session.lock:
                        session.shim_conn = None
                    session.status = "finished"
                    self.broadcast_experiment_list_to_uis()
            elif info and role == "ui":
                # Remove from global UI connections list
                self.ui_connections.discard(conn)
            try:
                conn.close()
            except Exception as e:
                logger.error(f"Error closing connection: {e}")

    def run_server(self) -> None:
        """Main server loop: accept clients and spawn handler threads."""
        _run_start = time.time()
        logger.info(f"run_server starting...")

        # Set up signal handlers to ensure clean shutdown (especially FileWatcher cleanup)
        def shutdown_handler(signum, frame):
            logger.info(f"Received signal {signum}")
            self.handle_shutdown()

        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)

        logger.info(f"Creating socket... ({time.time() - _run_start:.2f}s)")
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Try binding with retry logic and better error handling
        logger.info(f"Binding to {HOST}:{PORT}... ({time.time() - _run_start:.2f}s)")
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.server_sock.bind((HOST, PORT))
                break
            except OSError as e:
                if e.errno == 48 and attempt < max_retries - 1:  # Address already in use
                    logger.warning(
                        f"Port {PORT} in use, retrying in 2 seconds... (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(2)
                    continue
                else:
                    raise

        self.server_sock.listen()
        logger.info(f"Develop server listening on {HOST}:{PORT} ({time.time() - _run_start:.2f}s)")

        # Start inactivity monitor (shuts down after 1 hour of no messages)
        self._start_inactivity_monitor()

        # Load finished runs on startup
        logger.info(f"Loading finished runs... ({time.time() - _run_start:.2f}s)")
        self.load_finished_runs()
        logger.info(f"Server fully ready! ({time.time() - _run_start:.2f}s)")

        try:
            while True:
                conn, _ = self.server_sock.accept()
                threading.Thread(target=self.handle_client, args=(conn,), daemon=True).start()
        except OSError:
            # This will be triggered when server_sock is closed (on shutdown)
            pass
        finally:
            self._git_executor.shutdown(wait=False)
            self.server_sock.close()
            logger.info("Develop server stopped.")


if __name__ == "__main__":
    MainServer().run_server()
