"""
Server state management.

Holds all in-memory state, broadcasting logic, git versioning, and process spawning.
"""

import asyncio
import json
import os
import shlex
import shutil
import subprocess
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from sovara.common.logger import create_file_logger
from sovara.common.constants import (
    MAIN_SERVER_LOG,
    SERVER_INACTIVITY_TIMEOUT,
    SESSION_ORPHAN_TIMEOUT,
    SOVARA_GIT_DIR,
)
from sovara.server.database_manager import DB
from sovara.server.graph_models import SessionGraph

logger = create_file_logger(MAIN_SERVER_LOG)


class Session:
    """Represents a running so-record process."""

    def __init__(self, session_id: str, project_id: str = None, project_root: str = None):
        self.session_id = session_id
        self.project_id = project_id
        self.project_root = project_root
        self.status = "running"
        self.command: Optional[str] = None
        self.sse_connected = False
        self.registered_at = time.time()
        self.runtime_started_at: Optional[float] = None


class ServerState:
    """Manages all server state: sessions, graphs, connections."""

    EXPERIMENT_PAGE_SIZE = 50
    BROADCAST_DEBOUNCE_MS = 100

    def __init__(self):
        # Session state
        self.sessions: dict[str, Session] = {}
        self.session_graphs: dict[str, SessionGraph] = {}
        self.rerun_sessions: set[str] = set()
        # Runtime checkpointing can happen inside add-node handling, which
        # already holds this lock while mutating session_graphs.
        self.lock = threading.RLock()

        # WebSocket connections
        self.ui_websockets: set = set()  # set of WebSocket connections

        # SSE queues for runners (session_id -> asyncio.Queue)
        self.runner_event_queues: dict[str, asyncio.Queue] = {}

        # Inactivity tracking
        self._last_activity_time = time.time()

        # Debounced broadcast
        self._broadcast_timer: Optional[threading.Timer] = None
        self._broadcast_lock = threading.Lock()

        # asyncio loop reference (set during lifespan)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Reference to uvicorn.Server for clean shutdown via should_exit
        self._uvicorn_server = None

        # Git versioning
        self._git_available: Optional[bool] = None
        self._git_initialized_projects: set = set()
        self._git_base_dir = os.path.abspath(SOVARA_GIT_DIR)
        self._git_executor = ThreadPoolExecutor(max_workers=1)

    def touch_activity(self):
        """Reset inactivity timer."""
        self._last_activity_time = time.time()

    def check_inactivity(self) -> bool:
        """Return True if server should shut down due to inactivity."""
        return (time.time() - self._last_activity_time) >= SERVER_INACTIVITY_TIMEOUT

    def request_shutdown(self) -> None:
        """Request a clean server shutdown via uvicorn's should_exit flag."""
        if self._uvicorn_server:
            logger.info("Setting uvicorn should_exit=True for clean shutdown")
            self._uvicorn_server.should_exit = True
        else:
            logger.warning("No uvicorn server reference, cannot shut down cleanly")

    # ============================================================
    # Broadcasting
    # ============================================================

    async def broadcast_to_all_uis(self, msg: dict) -> None:
        """Broadcast a message to all UI WebSocket connections."""
        data = json.dumps(msg)
        for ws in list(self.ui_websockets):
            try:
                await ws.send_text(data)
            except Exception as e:
                logger.error(f"Error broadcasting to UI: {e}")
                self.ui_websockets.discard(ws)

    async def broadcast_graph_update(self, session_id: str) -> None:
        """Broadcast current graph state for a session to all UIs."""
        if session_id in self.session_graphs:
            graph = self.session_graphs[session_id].to_dict()
            await self.broadcast_to_all_uis({
                "type": "graph_update",
                "session_id": session_id,
                "payload": graph,
                "active_runtime_seconds": self.get_persisted_active_runtime_seconds(session_id),
            })

    def notify_project_list_changed(self) -> None:
        """Broadcast a signal so UIs refetch their project list."""
        self.schedule_broadcast({"type": "project_list_changed"})

    def notify_user_changed(self) -> None:
        """Broadcast a signal so UIs refetch the local user profile."""
        self.schedule_broadcast({"type": "user_changed"})

    def notify_experiment_list_changed(self) -> None:
        """Schedule a debounced broadcast of the experiment list."""
        with self._broadcast_lock:
            if self._broadcast_timer is not None:
                self._broadcast_timer.cancel()
            self._broadcast_timer = threading.Timer(
                self.BROADCAST_DEBOUNCE_MS / 1000,
                self._trigger_broadcast,
            )
            self._broadcast_timer.daemon = True
            self._broadcast_timer.start()

    def _trigger_broadcast(self) -> None:
        """Called by debounce timer -- schedules async broadcast on the event loop."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.broadcast_experiment_list_to_uis(), self._loop
            )

    async def broadcast_experiment_list_to_uis(self) -> None:
        """Broadcast running + first page of finished experiments to all UIs."""
        session_map, running_ids = self.get_session_snapshot()

        running_rows = DB.get_experiments_by_ids(running_ids)
        finished_rows = DB.get_experiments_excluding_ids(
            running_ids, limit=self.EXPERIMENT_PAGE_SIZE,
        )
        finished_count = DB.get_experiment_count_excluding_ids(running_ids)
        has_more = finished_count > self.EXPERIMENT_PAGE_SIZE

        experiments = [
            self._format_experiment_row(row, session_map)
            for row in running_rows + finished_rows
        ]
        await self.broadcast_to_all_uis(
            {"type": "experiment_list", "experiments": experiments, "has_more": has_more}
        )

    def _format_experiment_row(self, row, session_map) -> dict:
        """Convert a DB experiment row to a dict for the frontend."""
        row_dict = dict(row)
        session_id = row_dict["session_id"]
        session = session_map.get(session_id)
        status = session.status if session else "finished"

        timestamp = row_dict["timestamp"]
        if hasattr(timestamp, "isoformat"):
            timestamp = timestamp.isoformat()
        elif hasattr(timestamp, "strftime"):
            timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        else:
            try:
                dt = datetime.strptime(str(timestamp), "%Y-%m-%d %H:%M:%S")
                timestamp = dt.isoformat()
            except Exception:
                pass

        color_preview = []
        raw_color_preview = row_dict.get("color_preview")
        if isinstance(raw_color_preview, list):
            color_preview = raw_color_preview
        elif raw_color_preview:
            try:
                color_preview = json.loads(raw_color_preview)
            except Exception:
                color_preview = []

        return {
            "session_id": session_id,
            "status": status,
            "timestamp": timestamp,
            "runtime_seconds": DB._normalize_runtime_seconds(row_dict["runtime_seconds"]),
            "active_runtime_seconds": DB._normalize_runtime_seconds(row_dict["active_runtime_seconds"]),
            "color_preview": color_preview,
            "version_date": row_dict["version_date"],
            "run_name": row_dict["name"],
            "custom_metrics": DB._parse_custom_metrics(row_dict["custom_metrics"]),
            "thumb_label": DB._normalize_thumb_label(row_dict["thumb_label"]),
            "tags": row_dict.get("tags", []),
            "project_id": row_dict.get("project_id") or (session.project_id if session else None),
        }

    # ============================================================
    # Helpers
    # ============================================================

    def _clear_session_ui(self, session_id: str) -> None:
        """Clear UI state for a session (graphs and color previews)."""
        empty_graph = SessionGraph.empty()
        self.session_graphs[session_id] = empty_graph
        DB.update_graph_topology(session_id, empty_graph)
        DB.update_color_preview(session_id, [])

    def clear_session_ui_and_schedule_broadcast(self, session_id: str) -> None:
        """Clear UI state and schedule broadcast updates."""
        self._clear_session_ui(session_id)
        empty_graph = self.session_graphs[session_id]
        self.schedule_broadcast(
            {"type": "color_preview_update", "session_id": session_id, "color_preview": []}
        )
        self.schedule_broadcast({
            "type": "graph_update",
            "session_id": session_id,
            "payload": empty_graph.to_dict(),
            "active_runtime_seconds": self.get_persisted_active_runtime_seconds(session_id),
        })

    def start_session_attempt(
        self,
        session_id: str,
        project_id: str | None = None,
        project_root: str | None = None,
        clear_active_runtime: bool = True,
        reset_runner_connection: bool = False,
    ) -> Session:
        """Mark a session as actively running and reset its in-memory timer."""
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                session = Session(session_id, project_id=project_id, project_root=project_root)
                self.sessions[session_id] = session
            if project_id is not None:
                session.project_id = project_id
            if project_root is not None:
                session.project_root = project_root
            session.status = "running"
            session.runtime_started_at = time.perf_counter()
            if reset_runner_connection:
                session.sse_connected = False
                session.registered_at = time.time()
        if clear_active_runtime:
            DB.clear_active_runtime_seconds(session_id)
        return session

    def get_live_runtime_seconds(self, session_id: str) -> float | None:
        """Return the current elapsed runtime for a running session."""
        with self.lock:
            session = self.sessions.get(session_id)
            started_at = session.runtime_started_at if session else None
        if started_at is None:
            return None
        return max(0.0, time.perf_counter() - started_at)

    def get_persisted_active_runtime_seconds(self, session_id: str) -> float | None:
        """Return the last persisted active runtime checkpoint for a session."""
        row = DB.get_experiment_detail(session_id)
        if row is None:
            return None
        return DB._normalize_runtime_seconds(row["active_runtime_seconds"])

    def checkpoint_session_runtime(self, session_id: str) -> float | None:
        """Persist the current runtime checkpoint for a live session."""
        elapsed = self.get_live_runtime_seconds(session_id)
        if elapsed is None:
            return None
        DB.update_active_runtime_seconds(session_id, elapsed)
        return elapsed

    def finalize_session_runtime(self, session_id: str) -> float | None:
        """Finalize the current run attempt and preserve the first canonical runtime."""
        elapsed = self.get_live_runtime_seconds(session_id)
        if elapsed is None:
            return None
        DB.finalize_runtime(session_id, elapsed)
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                session.runtime_started_at = None
        return elapsed

    def checkpoint_interrupted_session_runtime(self, session_id: str) -> float | None:
        """Persist the best-known runtime for an interrupted attempt without finalizing it."""
        elapsed = self.get_live_runtime_seconds(session_id)
        if elapsed is None:
            return None
        DB.update_active_runtime_seconds(session_id, elapsed)
        with self.lock:
            session = self.sessions.get(session_id)
            if session:
                session.runtime_started_at = None
        return elapsed

    def sweep_dead_sessions(self) -> list[str]:
        """Mark sessions whose runner died before SSE connected as finished."""
        now = time.time()
        swept_session_ids: list[str] = []
        for session in list(self.sessions.values()):
            if (
                session.status == "running"
                and session.session_id in self.runner_event_queues
                and not session.sse_connected
                and now - session.registered_at > SESSION_ORPHAN_TIMEOUT
            ):
                logger.info(f"Sweeping orphaned session {session.session_id}")
                self.checkpoint_interrupted_session_runtime(session.session_id)
                session.status = "finished"
                self.runner_event_queues.pop(session.session_id, None)
                swept_session_ids.append(session.session_id)
        return swept_session_ids

    def _sweep_dead_sessions(self) -> list[str]:
        """Backward-compatible alias for the public orphan-session sweep."""
        return self.sweep_dead_sessions()

    def get_session_snapshot(self) -> tuple[dict[str, Session], set[str]]:
        """Return a fresh snapshot of sessions after reconciling orphaned runners."""
        self.sweep_dead_sessions()
        with self.lock:
            session_map = dict(self.sessions)
        running_ids = {sid for sid, session in session_map.items() if session.status == "running"}
        return session_map, running_ids

    def load_finished_runs(self) -> None:
        """Load finished runs from database into sessions dict."""
        try:
            rows = DB.get_finished_runs()
            for row in rows:
                session_id = row["session_id"]
                if session_id not in self.sessions:
                    session = Session(session_id)
                    session.status = "finished"
                    self.sessions[session_id] = session
        except Exception as e:
            logger.warning(f"Failed to load finished runs: {e}")

    # ============================================================
    # Git Versioning
    # ============================================================

    def _is_git_available(self) -> bool:
        if self._git_available is None:
            self._git_available = shutil.which("git") is not None
            if not self._git_available:
                logger.warning("git not found, code versioning disabled")
        return self._git_available

    def _git_dir_for_project(self, project_id: str) -> str:
        return os.path.join(self._git_base_dir, project_id)

    def _run_git(self, project_id: str, project_root: str, *args, check=True):
        git_dir = self._git_dir_for_project(project_id)
        env = os.environ.copy()
        env["GIT_DIR"] = git_dir
        env["GIT_WORK_TREE"] = project_root
        return subprocess.run(
            ["git"] + list(args),
            env=env, cwd=project_root, check=check,
            capture_output=True, text=True, timeout=30,
        )

    @staticmethod
    def _serialize_git_commit_timestamp(raw_timestamp: str) -> Optional[str]:
        try:
            dt = datetime.fromisoformat(raw_timestamp.strip())
        except ValueError:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return DB._serialize_timestamp(dt.astimezone(timezone.utc))

    def _get_head_commit_timestamp(self, project_id: str, project_root: str) -> Optional[str]:
        result = self._run_git(project_id, project_root, "log", "-1", "--format=%cI", "HEAD")
        return self._serialize_git_commit_timestamp(result.stdout)

    def _ensure_git_initialized(self, project_id: str, project_root: str) -> bool:
        if project_id in self._git_initialized_projects:
            return True
        if not self._is_git_available():
            return False

        git_dir = self._git_dir_for_project(project_id)
        try:
            lock_file = os.path.join(git_dir, "index.lock")
            if os.path.exists(lock_file):
                os.remove(lock_file)
                logger.info(f"Removed stale git index.lock for project {project_id}")

            if os.path.exists(os.path.join(git_dir, "HEAD")):
                self._git_initialized_projects.add(project_id)
                return True

            os.makedirs(git_dir, exist_ok=True)
            self._run_git(project_id, project_root, "init")
            self._run_git(project_id, project_root, "config", "user.name", "Sovara Code Versioner")
            self._run_git(project_id, project_root, "config", "user.email", "sovara@localhost")
            self._git_initialized_projects.add(project_id)
            return True
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"Failed to init git: {e}")
            return False

    def _commit_and_get_version_timestamp(self, project_id: str, project_root: str) -> Optional[str]:
        if not self._ensure_git_initialized(project_id, project_root):
            return None
        try:
            self._run_git(project_id, project_root, "add", ".")
            result = self._run_git(project_id, project_root, "diff", "--cached", "--quiet", check=False)

            if result.returncode != 0:
                now = datetime.now(timezone.utc)
                self._run_git(project_id, project_root, "commit", "-m", now.isoformat(timespec="seconds"))

            return self._get_head_commit_timestamp(project_id, project_root)
        except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
            logger.error(f"Git operation failed: {e}")
            return None

    def _do_git_version(self, session_id: str, project_id: str, project_root: str) -> None:
        """Background thread: commit files and update experiment version_date."""
        version_date = self._commit_and_get_version_timestamp(project_id, project_root)
        if version_date:
            DB.update_experiment_version_date(session_id, version_date)
        self.notify_experiment_list_changed()

    def request_git_version(self, session_id: str, project_id: str, project_root: str) -> None:
        """Submit async git versioning in the background."""
        self._git_executor.submit(self._do_git_version, session_id, project_id, project_root)

    # ============================================================
    # Process Spawning
    # ============================================================

    def spawn_session_process(self, session_id: str, child_session_id: str) -> None:
        """Spawn a new session process with the original command and environment."""
        try:
            cwd, command, environment = DB.get_exec_command(session_id)
            if not command:
                return

            self.rerun_sessions.add(child_session_id)

            env = os.environ.copy()
            env["SOVARA_SESSION_ID"] = session_id
            env.update(environment)

            args = shlex.split(command)
            subprocess.Popen(args, cwd=cwd, env=env, close_fds=True, start_new_session=True)

            session = self.sessions.get(child_session_id)
            if session:
                session.status = "running"
                DB.update_timestamp(child_session_id, datetime.now(timezone.utc))
                self.notify_experiment_list_changed()

        except Exception as e:
            logger.error(f"Failed to spawn session process: {e}")

    # ============================================================
    # Runner SSE events
    # ============================================================

    async def send_runner_event(self, session_id: str, event: dict) -> None:
        """Push an event to a runner's SSE queue."""
        q = self.runner_event_queues.get(session_id)
        if q:
            await q.put(event)
        else:
            logger.warning(f"No SSE queue for session {session_id}")

    # ============================================================
    # Sync scheduling helpers (for use from def endpoints in thread pool)
    # ============================================================

    def _can_schedule(self) -> bool:
        return self._loop is not None and self._loop.is_running()

    # Cosmetic: we only create the coroutine after checking the loop is running,
    # to avoid "coroutine was never awaited" RuntimeWarnings during startup/shutdown.

    def schedule_broadcast(self, msg: dict) -> None:
        """Schedule a broadcast to all UIs from sync context."""
        if self._can_schedule():
            asyncio.run_coroutine_threadsafe(self.broadcast_to_all_uis(msg), self._loop)

    def schedule_graph_update(self, session_id: str) -> None:
        """Schedule a graph update broadcast from sync context."""
        if self._can_schedule():
            asyncio.run_coroutine_threadsafe(self.broadcast_graph_update(session_id), self._loop)

    def schedule_runner_event(self, session_id: str, event: dict) -> None:
        """Schedule an SSE event push from sync context."""
        if self._can_schedule():
            asyncio.run_coroutine_threadsafe(self.send_runner_event(session_id, event), self._loop)
