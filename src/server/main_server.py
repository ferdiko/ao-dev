import socket
import os
import json
import threading
import subprocess
import time
import uuid
import shlex
import signal
import multiprocessing
from datetime import datetime
from typing import Optional, Dict

from ao.common.logger import create_file_logger
from ao.common.constants import (
    AO_CONFIG,
    MAIN_SERVER_LOG,
    HOST,
    PORT,
    SERVER_INACTIVITY_TIMEOUT,
    PLAYBOOK_SERVER_URL,
    PLAYBOOK_API_KEY,
)
from ao.server.database_manager import DB
from ao.server.file_watcher import run_file_watcher_process

logger = create_file_logger(MAIN_SERVER_LOG)


def send_json(conn: socket.socket, msg: dict) -> None:
    try:
        msg_type = msg.get("type", "unknown")
        logger.debug(f"Sent message type: {msg_type}")
        conn.sendall((json.dumps(msg) + "\n").encode("utf-8"))
    except Exception as e:
        logger.error(f"Error sending JSON: {e}")


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
        _init_start = time.time()
        logger.info(f"__init__ starting...")
        self.server_sock = None
        self.lock = threading.Lock()
        self.conn_info = {}  # conn -> {role, session_id}
        self.session_graphs = {}  # session_id -> graph_data
        self.ui_connections = set()
        self.sessions = {}  # session_id -> Session (only for agent runner connections)
        self.file_watcher_process = None  # Child process for file watching
        self.file_watch_queue = multiprocessing.Queue()  # MainServer → FileWatcher
        self.file_watch_response_queue = multiprocessing.Queue()  # FileWatcher → MainServer
        # self.current_user_id = None  # Store the current authenticated user_id (auth disabled)
        self.rerun_sessions = set()  # Track sessions being rerun to avoid clearing llm_calls
        self._last_activity_time = time.time()  # Track last message received for inactivity timeout
        self._project_root = None  # Workspace root from VS Code UI

    # ============================================================
    # File Watcher Management
    # ============================================================

    def start_file_watcher(self) -> None:
        """Start the file watcher process."""
        if self.file_watcher_process and self.file_watcher_process.is_alive():
            logger.warning("File watcher process is already running")
            return

        try:
            # Use workspace root from VS Code UI, or fall back to config
            from ao.common.constants import AO_PROJECT_ROOT

            project_root = self._project_root or AO_PROJECT_ROOT

            self.file_watcher_process = multiprocessing.Process(
                target=run_file_watcher_process,
                args=(project_root, self.file_watch_queue, self.file_watch_response_queue),
                daemon=True,  # Dies when parent process dies
            )
            self.file_watcher_process.start()

            # Give it a moment to start
            time.sleep(0.1)
            if not self.file_watcher_process.is_alive():
                logger.error(f"File watcher process died immediately")

        except Exception as e:
            logger.error(f"✗ Failed to start file watcher process: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")

    def stop_file_watcher(self) -> None:
        """Stop the file watcher process if it's running."""
        if self.file_watcher_process and self.file_watcher_process.is_alive():
            try:
                self.file_watcher_process.terminate()
                self.file_watcher_process.join(timeout=2)  # Wait up to 2 seconds
                if self.file_watcher_process.is_alive():
                    # Force kill if it doesn't terminate gracefully
                    self.file_watcher_process.kill()
                    self.file_watcher_process.join()
            except Exception as e:
                logger.error(f"Error stopping file watcher process: {e}")
            finally:
                self.file_watcher_process = None

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

    def _start_response_queue_monitor(self) -> None:
        """Start a daemon thread that polls the FileWatcher response queue."""
        import queue

        def monitor_response_queue():
            while True:
                try:
                    msg = self.file_watch_response_queue.get(timeout=1.0)
                    msg_type = msg.get("type")
                    if msg_type == "version_result":
                        # FileWatcher completed git commit, update DB and broadcast
                        session_id = msg.get("session_id")
                        version_date = msg.get("version_date")
                        if session_id and version_date:
                            DB.update_experiment_version_date(session_id, version_date)
                        self.broadcast_experiment_list_to_uis()
                    else:
                        logger.warning(f"Unknown response queue message type: {msg_type}")
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Error processing response queue: {e}")

        thread = threading.Thread(target=monitor_response_queue, daemon=True)
        thread.start()

    # ============================================================
    # Utils
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

        # If a specific conn is provided, send experiments filtered by that conn's user
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

    # ============================================================
    # Handle message types.
    # ============================================================

    def load_finished_runs(self):
        # Load only session_id and timestamp for finished runs
        try:
            rows = DB.get_finished_runs()
            for row in rows:
                session_id = row["session_id"]
                # Mark as finished (not running)
                session = self.sessions.get(session_id)
                if not session:
                    session = Session(session_id)
                    session.status = "finished"
                    self.sessions[session_id] = session
        except Exception as e:
            logger.warning(f"Failed to load finished runs from database: {e}")

    def handle_graph_request(self, conn, session_id):
        # Check if we have in-memory graph first (most up-to-date)
        if session_id in self.session_graphs:
            graph = self.session_graphs[session_id]
            send_json(conn, {"type": "graph_update", "session_id": session_id, "payload": graph})
            return

        # Fall back to database if no in-memory graph
        row = DB.get_graph(session_id)
        if row and row["graph_topology"]:
            graph = json.loads(row["graph_topology"])
            self.session_graphs[session_id] = graph
            send_json(conn, {"type": "graph_update", "session_id": session_id, "payload": graph})

    def _find_sessions_with_node(self, node_id: str) -> set:
        """Find all sessions containing a specific node ID. Returns empty set if not found."""
        sessions = set()
        for session_id, graph in self.session_graphs.items():
            if any(node["id"] == node_id for node in graph.get("nodes", [])):
                sessions.add(session_id)
        return sessions

    def handle_add_node(self, msg: dict) -> None:
        sid = msg["session_id"]
        node = msg["node"]
        incoming_edges = msg.get("incoming_edges", [])

        # Check if any incoming edges reference nodes from other sessions
        cross_session_sources = []
        target_sessions = set()

        for source in incoming_edges:
            # Find which session contains this source node
            source_sessions = self._find_sessions_with_node(source)
            if source_sessions:
                for source_session in source_sessions:
                    target_sessions.add(source_session)
                    cross_session_sources.append(source)

        # If we have cross-session references, add the node to those sessions instead of current session
        if target_sessions:
            for target_sid in target_sessions:
                self._add_node_to_session(target_sid, node, cross_session_sources)
        else:
            # No cross-session references, add to current session as normal
            self._add_node_to_session(sid, node, incoming_edges)

    def _add_node_to_session(self, sid: str, node: dict, incoming_edges: list) -> None:
        """Add a node to a specific session's graph"""
        # Add or update the node
        graph = self.session_graphs.setdefault(sid, {"nodes": [], "edges": []})

        # Check for duplicate node
        node_exists = False
        for n in graph["nodes"]:
            if n["id"] == node["id"]:
                node_exists = True
                break
        if not node_exists:
            graph["nodes"].append(node)

        # Build set of existing edge IDs for duplicate checking
        existing_edge_ids = {e["id"] for e in graph["edges"]}
        existing_node_ids = {n["id"] for n in graph["nodes"]}

        # Add incoming edges (only if source nodes exist and edge doesn't already exist)
        for source in incoming_edges:
            if source in existing_node_ids:
                target = node["id"]
                edge_id = f"e{source}-{target}"
                if edge_id not in existing_edge_ids:
                    full_edge = {"id": edge_id, "source": source, "target": target}
                    graph["edges"].append(full_edge)
                    existing_edge_ids.add(edge_id)  # Track newly added edge
                    logger.info(f"Added edge {edge_id} in session {sid}")
                else:
                    logger.debug(f"Skipping duplicate edge {edge_id}")
            else:
                logger.debug(f"Skipping edge from non-existent node {source} to {node['id']}")

        # Update color preview in database
        node_colors = [n["border_color"] for n in graph["nodes"]]
        color_preview = node_colors[-6:]  # Only display last 6 colors
        DB.update_color_preview(sid, color_preview)
        # Broadcast color preview update to all UIs
        self.broadcast_to_all_uis(
            {"type": "color_preview_update", "session_id": sid, "color_preview": color_preview}
        )
        self.broadcast_graph_update(sid)
        DB.update_graph_topology(sid, graph)

    def handle_edit_input(self, msg: dict) -> None:
        session_id = msg["session_id"]
        node_id = msg["node_id"]
        new_input = msg["value"]

        logger.info(f"[EditIO] edit input msg keys {[*msg.keys()]}")
        logger.info(f"[EditIO] edit input msg: {msg}")

        DB.set_input_overwrite(session_id, node_id, new_input)
        if session_id in self.session_graphs:
            for node in self.session_graphs[session_id]["nodes"]:
                if node["id"] == node_id:
                    node["input"] = new_input
                    break
            DB.update_graph_topology(session_id, self.session_graphs[session_id])
            self.broadcast_graph_update(session_id)

    def handle_edit_output(self, msg: dict) -> None:
        session_id = msg["session_id"]
        node_id = msg["node_id"]
        new_output = msg["value"]

        logger.info(f"[EditIO] edit output msg: {msg}")

        DB.set_output_overwrite(session_id, node_id, new_output)
        if session_id in self.session_graphs:
            for node in self.session_graphs[session_id]["nodes"]:
                if node["id"] == node_id:
                    node["output"] = new_output
                    break
            DB.update_graph_topology(session_id, self.session_graphs[session_id])
            self.broadcast_graph_update(session_id)

    def handle_update_node(self, msg: dict) -> None:
        """Handle updateNode message for updating node properties like label"""
        session_id = msg.get("session_id")
        node_id = msg.get("node_id")
        field = msg.get("field")
        value = msg.get("value")

        if not all([session_id, node_id, field]):
            logger.error(f"Missing required fields in updateNode message: {msg}")
            return

        if session_id in self.session_graphs:
            for node in self.session_graphs[session_id]["nodes"]:
                if node["id"] == node_id:
                    # Update the specified field
                    node[field] = value
                    break

            # Update the graph topology and broadcast the change
            DB.update_graph_topology(session_id, self.session_graphs[session_id])
            self.broadcast_graph_update(session_id)
        else:
            logger.warning(f"Session {session_id} not found in session_graphs")

    def handle_log(self, msg: dict) -> None:
        session_id = msg["session_id"]
        success = msg["success"]
        entry = msg["entry"]
        DB.add_log(session_id, success, entry)

        self.broadcast_experiment_list_to_uis()

    def handle_update_run_name(self, msg: dict) -> None:
        session_id = msg.get("session_id")
        run_name = msg.get("run_name")
        if session_id and run_name is not None:
            DB.update_run_name(session_id, run_name)
            self.broadcast_experiment_list_to_uis()
        else:
            logger.error(
                f"handle_update_run_name: Missing required fields: session_id={session_id}, run_name={run_name}"
            )

    def handle_update_result(self, msg: dict) -> None:
        session_id = msg.get("session_id")
        result = msg.get("result")
        if session_id and result is not None:
            DB.update_result(session_id, result)
            self.broadcast_experiment_list_to_uis()
        else:
            logger.error(
                f"handle_update_result: Missing required fields: session_id={session_id}, result={result}"
            )

    def handle_update_notes(self, msg: dict) -> None:
        session_id = msg.get("session_id")
        notes = msg.get("notes")
        if session_id and notes is not None:
            DB.update_notes(session_id, notes)
            self.broadcast_experiment_list_to_uis()
        else:
            logger.error(
                f"handle_update_notes: Missing required fields: session_id={session_id}, notes={notes}"
            )

    def handle_update_command(self, msg: dict) -> None:
        """Update the restart command for a session (sent async after handshake)."""
        session_id = msg.get("session_id")
        command = msg.get("command")
        if session_id and command:
            session = self.sessions.get(session_id)
            if session:
                session.command = command
                DB.update_command(session_id, command)

    def handle_get_graph(self, msg: dict, conn: socket.socket) -> None:
        session_id = msg["session_id"]

        self.handle_graph_request(conn, session_id)

    def handle_get_all_experiments(self, conn: socket.socket) -> None:
        """Handle request to refresh the experiment list (e.g., when VS Code window regains focus)."""
        # First, send current session_id and database_mode to ensure UI state is synced
        # This handles the case where the webview was recreated (e.g., tab switch) and needs state restoration
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
        # Then send the experiment list
        self.broadcast_experiment_list_to_uis(conn)

    # ============================================================
    # Lessons (proxied to ao-playbook API)
    # ============================================================

    def _playbook_request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make HTTP request to ao-playbook server."""
        import urllib.request
        import urllib.error

        url = f"{PLAYBOOK_SERVER_URL}/api/v1{endpoint}"
        headers = {"Content-Type": "application/json"}
        if PLAYBOOK_API_KEY:
            headers["X-API-Key"] = PLAYBOOK_API_KEY

        logger.info(f"[Playbook] {method} {url} (API key: {'set' if PLAYBOOK_API_KEY else 'NOT SET'})")

        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
                if isinstance(result, dict):
                    logger.info(f"[Playbook] Response status: {result.get('status', 'ok')}")
                else:
                    logger.info(f"[Playbook] Response: list with {len(result)} items")
                return result
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            logger.error(f"Playbook API error {e.code}: {error_body}")
            return {"error": f"API error: {e.code}", "detail": error_body}
        except urllib.error.URLError as e:
            logger.warning(f"Playbook server unavailable: {e.reason}")
            return {"error": "Playbook server unavailable"}
        except Exception as e:
            logger.error(f"Playbook request failed: {e}")
            return {"error": str(e)}

    def _merge_lessons_with_applied(self, lessons: list) -> list:
        """Merge ao-playbook lessons with local applied data."""
        # Get all applied records grouped by lesson_id
        applied_records = DB.get_all_lessons_applied()
        applied_by_lesson = {}
        for record in applied_records:
            lid = record["lesson_id"]
            if lid not in applied_by_lesson:
                applied_by_lesson[lid] = []
            applied_by_lesson[lid].append({
                "sessionId": record["session_id"],
                "nodeId": record["node_id"],
                "runName": record["run_name"],
            })

        # Merge applied data into lessons
        for lesson in lessons:
            lesson_id = lesson.get("id")
            if lesson_id and lesson_id in applied_by_lesson:
                lesson["appliedTo"] = applied_by_lesson[lesson_id]

        return lessons

    def handle_get_lessons(self, conn: socket.socket) -> None:
        """Fetch lessons from ao-playbook and merge with local applied data."""
        result = self._playbook_request("GET", "/lessons")

        if "error" in result:
            send_json(conn, {"type": "lessons_list", "lessons": [], "error": result["error"]})
            return

        # Handle both list response and dict with "lessons" key
        lessons = result if isinstance(result, list) else result.get("lessons", [])
        merged = self._merge_lessons_with_applied(lessons)
        send_json(conn, {"type": "lessons_list", "lessons": merged})

    def handle_add_lesson(self, msg: dict, conn: socket.socket) -> None:
        """Create lesson via ao-playbook API with validation feedback."""
        data = {
            "name": msg.get("name", ""),
            "summary": msg.get("summary", ""),
            "content": msg.get("content", ""),
            "path": msg.get("path", ""),
        }

        if not data["name"] or not data["content"]:
            logger.error("add_lesson: Missing required fields (name, content)")
            send_json(conn, {"type": "lesson_error", "error": "Missing required fields (name, content)"})
            return

        # Use force query param to skip server-side validation
        force = msg.get("force", False)
        endpoint = "/lessons" + ("?force=true" if force else "")

        result = self._playbook_request("POST", endpoint, data)

        if result.get("status") == "rejected":
            # Validation rejection - keep modal open, include hint if present
            reason = result.get("reason", "Validation failed")
            hint = result.get("hint")
            if hint:
                reason = f"{reason}\n\nHint: {hint}"
            send_json(conn, {
                "type": "lesson_rejected",
                "reason": reason,
                "severity": "error",
                "conflicting_lesson_ids": result.get("conflicting_lesson_ids", []),
            })
        elif "error" in result:
            send_json(conn, {"type": "lesson_error", "error": result.get("error", "Unknown error")})
        elif result.get("status") == "created":
            # Success - include validation feedback
            validation = result.get("validation")
            send_json(conn, {
                "type": "lesson_created",
                "lesson": result,
                "validation": validation,
            })
            self._broadcast_lessons_to_uis()
        else:
            logger.warning(f"Unexpected add_lesson response: {result}")
            send_json(conn, {"type": "lesson_error", "error": "Unexpected server response"})

    def handle_update_lesson(self, msg: dict, conn: socket.socket) -> None:
        """Update lesson via ao-playbook API with validation feedback."""
        lesson_id = msg.get("lesson_id")
        if not lesson_id:
            logger.error("update_lesson: Missing lesson_id")
            send_json(conn, {"type": "lesson_error", "error": "Missing lesson_id"})
            return

        # Only include fields that were provided
        data = {}
        for field in ["name", "summary", "content", "path"]:
            if field in msg:
                data[field] = msg[field]

        if not data:
            logger.error("update_lesson: No fields to update")
            send_json(conn, {"type": "lesson_error", "error": "No fields to update"})
            return

        # Use force query param to skip server-side validation
        force = msg.get("force", False)
        endpoint = f"/lessons/{lesson_id}" + ("?force=true" if force else "")

        result = self._playbook_request("PUT", endpoint, data)

        if result.get("status") == "rejected":
            # Validation rejection - keep modal open, include hint if present
            reason = result.get("reason", "Validation failed")
            hint = result.get("hint")
            if hint:
                reason = f"{reason}\n\nHint: {hint}"
            send_json(conn, {
                "type": "lesson_rejected",
                "reason": reason,
                "severity": "error",
                "conflicting_lesson_ids": result.get("conflicting_lesson_ids", []),
            })
        elif "error" in result:
            send_json(conn, {"type": "lesson_error", "error": result.get("error", "Unknown error")})
        elif result.get("status") == "updated":
            # Success - include validation feedback
            validation = result.get("validation")
            send_json(conn, {
                "type": "lesson_updated",
                "lesson": result,
                "validation": validation,
            })
            self._broadcast_lessons_to_uis()
        else:
            logger.warning(f"Unexpected update_lesson response: {result}")
            send_json(conn, {"type": "lesson_error", "error": "Unexpected server response"})

    def handle_delete_lesson(self, msg: dict, conn: socket.socket) -> None:
        """Delete lesson via ao-playbook API and clean up local applied records."""
        lesson_id = msg.get("lesson_id")
        if not lesson_id:
            logger.error("delete_lesson: Missing lesson_id")
            send_json(conn, {"type": "lesson_error", "error": "Missing lesson_id"})
            return

        result = self._playbook_request("DELETE", f"/lessons/{lesson_id}")
        if "error" in result:
            send_json(conn, {"type": "lesson_error", "error": result.get("error", "Unknown error")})
        else:
            # Clean up local applied records
            DB.delete_lessons_applied_for_lesson(lesson_id)
            self._broadcast_lessons_to_uis()

    def handle_get_lesson(self, msg: dict, conn: socket.socket) -> None:
        """Fetch a single lesson's full content via ao-playbook API."""
        lesson_id = msg.get("lesson_id")
        if not lesson_id:
            logger.error("get_lesson: Missing lesson_id")
            send_json(conn, {"type": "lesson_error", "error": "Missing lesson_id"})
            return

        result = self._playbook_request("GET", f"/lessons/{lesson_id}")
        if "error" in result:
            send_json(conn, {"type": "lesson_error", "error": result.get("error", "Unknown error")})
        else:
            # Result contains the full lesson with content
            lesson = result.get("lesson", result)
            send_json(conn, {"type": "lesson_content", "lesson": lesson})

    def handle_folder_ls(self, msg: dict, conn: socket.socket) -> None:
        """List folder contents via ao-playbook POST /lessons/folders/ls."""
        path = msg.get("path", "")
        result = self._playbook_request("POST", "/lessons/folders/ls", {"path": path})

        if "error" in result:
            send_json(conn, {"type": "lesson_error", "error": result.get("error", "Unknown error")})
            return

        # Merge appliedTo data into the returned lessons
        lessons = result.get("lessons", [])
        merged = self._merge_lessons_with_applied(lessons)

        send_json(conn, {
            "type": "folder_ls_result",
            "path": path,
            "folders": result.get("folders", []),
            "lessons": merged,
            "lesson_count": result.get("lesson_count", 0),
        })

    def _broadcast_lessons_to_uis(self) -> None:
        """Signal all UIs to refresh their expanded folders."""
        self.broadcast_to_all_uis({"type": "lessons_refresh"})

    # NOTE: Auth disabled - handle_auth method commented out
    # def handle_auth(self, msg: dict, conn: socket.socket) -> None:
    #     """Handle auth messages from UI clients: attach user_id to connection and store current user."""
    #     try:
    #         user_id = msg.get("user_id")
    #         # Store the current authenticated user_id on the server
    #         self.current_user_id = user_id
    #         info = self.conn_info.get(conn)
    #         if info is None:
    #             self.conn_info[conn] = {"role": "ui", "session_id": None, "user_id": user_id}
    #         else:
    #             info["user_id"] = user_id
    #         # Send filtered list to this connection
    #         self.broadcast_experiment_list_to_uis(conn)
    #     except Exception as e:
    #         logger.error(f"Error handling auth message: {e}")

    def handle_add_subrun(self, msg: dict, conn: socket.socket) -> None:
        # If rerun, use previous session_id. Else, assign new one.
        prev_session_id = msg.get("prev_session_id")
        if prev_session_id:
            session_id = prev_session_id
        else:
            session_id = str(uuid.uuid4())
            # Insert new experiment into DB.
            cwd = msg.get("cwd")
            command = msg.get("command")
            environment = msg.get("environment")
            timestamp = datetime.now()
            name = msg.get("name")
            if not name:
                run_index = DB.get_next_run_index()
                name = f"Run {run_index}"
            parent_session_id = msg.get("parent_session_id")
            # NOTE: Auth disabled - user_id handling commented out
            # user_id = msg.get("user_id")
            # if user_id is None:
            #     user_id = self.current_user_id

            # Create experiment with version_date=None, request async versioning
            DB.add_experiment(
                session_id,
                name,
                timestamp,
                cwd,
                command,
                environment,
                parent_session_id,
                None,  # user_id disabled
                None,  # version_date will be set async by FileWatcher
            )
            # Request async git versioning from FileWatcher
            self.file_watch_queue.put({"type": "request_version", "session_id": session_id})
        # Insert session if not present.
        with self.lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = Session(session_id)
            session = self.sessions[session_id]
        with session.lock:
            session.shim_conn = conn
        session.status = "running"
        self.conn_info[conn] = {"role": "agent-runner", "session_id": session_id}
        response = {"type": "session_id", "session_id": session_id}
        request_id = msg.get("request_id")
        if request_id:
            response["request_id"] = request_id
        send_json(conn, response)
        self.broadcast_experiment_list_to_uis()

    def handle_erase(self, msg):
        session_id = msg.get("session_id")

        DB.erase(session_id)
        # Clear color preview in database
        DB.update_color_preview(session_id, [])

        # Broadcast color preview clearing to all UIs
        self.broadcast_to_all_uis(
            {"type": "color_preview_update", "session_id": session_id, "color_preview": []}
        )

        self.handle_restart_message({"session_id": session_id})

    def handle_restart_message(self, msg: dict) -> bool:
        session_id = msg.get("session_id")
        parent_session_id = DB.get_parent_session_id(session_id)
        if not parent_session_id:
            logger.error("Restart message missing session_id. Ignoring.")
            return
        # Clear UI state (updates both memory and database atomically)
        self._clear_session_ui(session_id)

        session = self.sessions.get(parent_session_id)

        if session and session.status == "running":
            # Send graceful restart signal to existing session if still connected
            if session.shim_conn:
                restart_msg = {"type": "restart", "session_id": parent_session_id}
                logger.debug(
                    f"Session running...Sending restart for session_id: {parent_session_id}"
                )
                try:
                    send_json(session.shim_conn, restart_msg)
                except Exception as e:
                    logger.error(f"Error sending restart: {e}")
                return
            else:
                logger.warning(f"No shim_conn for session_id: {parent_session_id}")
        elif session and session.status == "finished":
            # Rerun for finished session: spawn new process with same session_id
            self._spawn_session_process(parent_session_id, session_id)

    def handle_deregister_message(self, msg: dict) -> bool:
        session_id = msg["session_id"]
        session = self.sessions.get(session_id)
        if session:
            session.status = "finished"
            self.broadcast_experiment_list_to_uis()

    def handle_shutdown(self) -> None:
        """Handle shutdown command by closing all connections."""
        logger.info("Shutdown command received. Closing all connections.")
        # Close all client sockets
        for s in list(self.conn_info.keys()):
            try:
                s.close()
            except Exception as e:
                logger.error(f"Error closing socket: {e}")
        # Close server socket to break the accept() loop in run_server.
        # Cleanup (file watcher, queues) happens in run_server's finally block.
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass

    def handle_clear(self):
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
        # NOTE: Auth disabled - auth message handling commented out
        # if msg_type == "auth":
        #     self.handle_auth(msg, conn)
        if msg_type == "shutdown":
            self.handle_shutdown()
        elif msg_type == "restart":
            self.handle_restart_message(msg)
        elif msg_type == "deregister":
            self.handle_deregister_message(msg)
        elif msg_type == "add_node":
            self.handle_add_node(msg)
        elif msg_type == "edit_input":
            self.handle_edit_input(msg)
        elif msg_type == "edit_output":
            self.handle_edit_output(msg)
        elif msg_type == "update_node":
            self.handle_update_node(msg)
        elif msg_type == "log":
            self.handle_log(msg)
        elif msg_type == "update_run_name":
            self.handle_update_run_name(msg)
        elif msg_type == "update_result":
            self.handle_update_result(msg)
        elif msg_type == "update_notes":
            self.handle_update_notes(msg)
        elif msg_type == "add_subrun":
            self.handle_add_subrun(msg, conn)
        elif msg_type == "get_graph":
            self.handle_get_graph(msg, conn)
        elif msg_type == "erase":
            self.handle_erase(msg)
        elif msg_type == "clear":
            self.handle_clear()
        elif msg_type == "set_database_mode":
            self.handle_set_database_mode(msg)
        elif msg_type == "get_all_experiments":
            self.handle_get_all_experiments(conn)
        elif msg_type == "update_command":
            self.handle_update_command(msg)
        elif msg_type == "watch_file":
            self.handle_watch_file(msg)
        elif msg_type == "get_lessons":
            self.handle_get_lessons(conn)
        elif msg_type == "add_lesson":
            self.handle_add_lesson(msg, conn)
        elif msg_type == "update_lesson":
            self.handle_update_lesson(msg, conn)
        elif msg_type == "delete_lesson":
            self.handle_delete_lesson(msg, conn)
        elif msg_type == "get_lesson":
            self.handle_get_lesson(msg, conn)
        elif msg_type == "folder_ls":
            self.handle_folder_ls(msg, conn)
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
                        None,  # version_date will be set async by FileWatcher
                    )
                    # Request async git versioning from FileWatcher
                    self.file_watch_queue.put({"type": "request_version", "session_id": session_id})
                # Insert session if not present.
                with self.lock:
                    if session_id not in self.sessions:
                        self.sessions[session_id] = Session(session_id)
                    session = self.sessions[session_id]
                with session.lock:
                    session.shim_conn = conn
                session.status = "running"
                self.conn_info[conn] = {"role": role, "session_id": session_id}
                send_json(
                    conn,
                    {
                        "type": "session_id",
                        "session_id": session_id,
                        "database_mode": DB.get_current_mode(),
                    },
                )
                self.broadcast_experiment_list_to_uis()

            elif role == "ui":
                # Always reload finished runs from the DB before sending experiment list
                self.load_finished_runs()
                self.ui_connections.add(conn)
                # NOTE: Auth disabled - user_id handling commented out
                # user_id = handshake.get("user_id") if isinstance(handshake, dict) else None
                # if user_id is not None:
                #     self.current_user_id = user_id

                # Extract workspace_root from VS Code and update FileWatcher
                workspace_root = handshake.get("workspace_root")
                if workspace_root and workspace_root != self._project_root:
                    logger.info(f"Setting workspace root to: {workspace_root}")
                    self._project_root = workspace_root
                    # Restart file watcher with new project root
                    self.stop_file_watcher()
                    self.start_file_watcher()

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

        # Start file watcher process for AST recompilation
        logger.info(f"Starting file watcher... ({time.time() - _run_start:.2f}s)")
        self.start_file_watcher()

        # Start inactivity monitor (shuts down after 1 hour of no messages)
        self._start_inactivity_monitor()

        # Start response queue monitor (handles FileWatcher responses)
        self._start_response_queue_monitor()

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
            self.stop_file_watcher()
            for q in [self.file_watch_queue, self.file_watch_response_queue]:
                try:
                    q.close()
                    q.join_thread()
                except Exception:
                    pass
            try:
                self.server_sock.close()
            except Exception:
                pass
            logger.info("Develop server stopped.")


if __name__ == "__main__":
    MainServer().run_server()
