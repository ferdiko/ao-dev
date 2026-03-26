import asyncio
import time
import uuid
from datetime import datetime, timezone

from sovara.common.constants import SESSION_ORPHAN_TIMEOUT
from sovara.server.database_manager import DB
from sovara.server.routes.ui import (
    RestartRequest,
    get_experiment_detail,
    get_project_experiments,
    restart,
)
from sovara.server.state import ServerState


def _seed_experiment(session_id: str, project_id: str, *, parent_session_id: str | None = None) -> None:
    DB.upsert_project(project_id, f"Project {project_id[:8]}", "")
    DB.add_experiment(
        session_id,
        f"Run {session_id[:8]}",
        datetime.now(timezone.utc),
        "/tmp",
        "echo test",
        {},
        parent_session_id=parent_session_id,
        project_id=project_id,
    )


def _cleanup(project_id: str, *session_ids: str) -> None:
    DB.delete_runs(list(session_ids))
    DB.delete_project(project_id)


def _make_orphaned_session(state: ServerState, session_id: str, project_id: str):
    session = state.start_session_attempt(
        session_id,
        project_id=project_id,
        reset_runner_connection=True,
    )
    state.runner_event_queues[session_id] = asyncio.Queue()
    session.registered_at = time.time() - SESSION_ORPHAN_TIMEOUT - 1
    return session


def _get_project_experiments(project_id: str, state: ServerState):
    return get_project_experiments(
        project_id=project_id,
        limit=50,
        offset=0,
        sort="timestamp",
        dir="desc",
        name="",
        session_id="",
        label=[],
        tag_id=[],
        version=[],
        metric_filters="",
        time_from="",
        time_to="",
        state=state,
    )


def test_project_experiments_sweep_orphaned_session():
    project_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    state = ServerState()

    _seed_experiment(session_id, project_id)
    try:
        session = _make_orphaned_session(state, session_id, project_id)

        response = _get_project_experiments(project_id, state)

        assert response["running"] == []
        assert response["finished_total"] == 1
        assert [row["session_id"] for row in response["finished"]] == [session_id]
        assert response["finished"][0]["status"] == "finished"
        assert session.status == "finished"
        assert session_id not in state.runner_event_queues
    finally:
        _cleanup(project_id, session_id)


def test_experiment_detail_sweeps_orphaned_session_status():
    project_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    state = ServerState()

    _seed_experiment(session_id, project_id)
    try:
        session = _make_orphaned_session(state, session_id, project_id)

        response = get_experiment_detail(session_id=session_id, state=state)

        assert response["session_id"] == session_id
        assert response["status"] == "finished"
        assert session.status == "finished"
        assert session_id not in state.runner_event_queues
    finally:
        _cleanup(project_id, session_id)


def test_restart_sweeps_orphaned_parent_before_dispatch(monkeypatch):
    project_id = str(uuid.uuid4())
    parent_session_id = str(uuid.uuid4())
    child_session_id = str(uuid.uuid4())
    state = ServerState()

    _seed_experiment(parent_session_id, project_id)
    _seed_experiment(child_session_id, project_id, parent_session_id=parent_session_id)
    try:
        parent_session = _make_orphaned_session(state, parent_session_id, project_id)
        scheduled_events: list[tuple[str, dict]] = []
        spawned_sessions: list[tuple[str, str]] = []

        monkeypatch.setattr(
            state,
            "schedule_runner_event",
            lambda session_id, event: scheduled_events.append((session_id, event)),
        )
        monkeypatch.setattr(
            state,
            "spawn_session_process",
            lambda session_id, child_id: spawned_sessions.append((session_id, child_id)),
        )

        response = restart(RestartRequest(session_id=child_session_id), state)

        assert response == {"ok": True}
        assert scheduled_events == []
        assert spawned_sessions == [(parent_session_id, child_session_id)]
        assert parent_session.status == "finished"
        assert parent_session_id not in state.runner_event_queues
    finally:
        _cleanup(project_id, child_session_id, parent_session_id)


def test_restart_running_parent_without_queue_spawns_directly(monkeypatch):
    project_id = str(uuid.uuid4())
    parent_session_id = str(uuid.uuid4())
    child_session_id = str(uuid.uuid4())
    state = ServerState()

    _seed_experiment(parent_session_id, project_id)
    _seed_experiment(child_session_id, project_id, parent_session_id=parent_session_id)
    try:
        parent_session = state.start_session_attempt(
            parent_session_id,
            project_id=project_id,
            reset_runner_connection=True,
        )
        scheduled_events: list[tuple[str, dict]] = []
        spawned_sessions: list[tuple[str, str]] = []

        monkeypatch.setattr(
            state,
            "schedule_runner_event",
            lambda session_id, event: scheduled_events.append((session_id, event)),
        )
        monkeypatch.setattr(
            state,
            "spawn_session_process",
            lambda session_id, child_id: spawned_sessions.append((session_id, child_id)),
        )

        response = restart(RestartRequest(session_id=child_session_id), state)

        assert response == {"ok": True}
        assert scheduled_events == []
        assert spawned_sessions == [(parent_session_id, child_session_id)]
        assert parent_session.status == "finished"
    finally:
        _cleanup(project_id, child_session_id, parent_session_id)


def test_connected_runner_is_not_swept_from_project_experiments():
    project_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    state = ServerState()

    _seed_experiment(session_id, project_id)
    try:
        session = _make_orphaned_session(state, session_id, project_id)
        session.sse_connected = True

        response = _get_project_experiments(project_id, state)

        assert [row["session_id"] for row in response["running"]] == [session_id]
        assert response["finished"] == []
        assert session.status == "running"
        assert session_id in state.runner_event_queues
    finally:
        _cleanup(project_id, session_id)
