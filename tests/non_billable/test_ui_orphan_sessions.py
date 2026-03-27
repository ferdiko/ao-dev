import asyncio
import time
import uuid
from datetime import datetime, timezone

from sovara.common.constants import RUN_ORPHAN_TIMEOUT
from sovara.server.database_manager import DB
from sovara.server.routes.ui import (
    RestartRequest,
    get_run_detail,
    get_project_runs,
    restart,
)
from sovara.server.state import ServerState


def _seed_run(run_id: str, project_id: str, *, parent_run_id: str | None = None) -> None:
    DB.upsert_project(project_id, f"Project {project_id[:8]}", "")
    DB.add_run(
        run_id,
        f"Run {run_id[:8]}",
        datetime.now(timezone.utc),
        "/tmp",
        "echo test",
        {},
        parent_run_id=parent_run_id,
        project_id=project_id,
    )


def _cleanup(project_id: str, *run_ids: str) -> None:
    DB.delete_runs(list(run_ids))
    DB.delete_project(project_id)


def _make_orphaned_run(state: ServerState, run_id: str, project_id: str):
    run = state.start_run_attempt(
        run_id,
        project_id=project_id,
        reset_runner_connection=True,
    )
    state.runner_event_queues[run_id] = asyncio.Queue()
    run.registered_at = time.time() - RUN_ORPHAN_TIMEOUT - 1
    return run


def _get_project_runs(project_id: str, state: ServerState):
    return get_project_runs(
        project_id=project_id,
        limit=50,
        offset=0,
        sort="timestamp",
        dir="desc",
        name="",
        run_id="",
        label=[],
        tag_id=[],
        version=[],
        metric_filters="",
        time_from="",
        time_to="",
        state=state,
    )


def test_project_runs_sweep_orphaned_run():
    project_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    state = ServerState()

    _seed_run(run_id, project_id)
    try:
        run = _make_orphaned_run(state, run_id, project_id)

        response = _get_project_runs(project_id, state)

        assert response["running"] == []
        assert response["finished_total"] == 1
        assert [row["run_id"] for row in response["finished"]] == [run_id]
        assert response["finished"][0]["status"] == "finished"
        assert run.status == "finished"
        assert run_id not in state.runner_event_queues
    finally:
        _cleanup(project_id, run_id)


def test_run_detail_sweeps_orphaned_run_status():
    project_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    state = ServerState()

    _seed_run(run_id, project_id)
    try:
        run = _make_orphaned_run(state, run_id, project_id)

        response = get_run_detail(run_id=run_id, state=state)

        assert response["run_id"] == run_id
        assert response["status"] == "finished"
        assert run.status == "finished"
        assert run_id not in state.runner_event_queues
    finally:
        _cleanup(project_id, run_id)


def test_restart_sweeps_orphaned_parent_before_dispatch(monkeypatch):
    project_id = str(uuid.uuid4())
    parent_run_id = str(uuid.uuid4())
    child_run_id = str(uuid.uuid4())
    state = ServerState()

    _seed_run(parent_run_id, project_id)
    _seed_run(child_run_id, project_id, parent_run_id=parent_run_id)
    try:
        parent_run = _make_orphaned_run(state, parent_run_id, project_id)
        scheduled_events: list[tuple[str, dict]] = []
        spawned_runs: list[tuple[str, str]] = []

        monkeypatch.setattr(
            state,
            "schedule_runner_event",
            lambda run_id, event: scheduled_events.append((run_id, event)),
        )
        monkeypatch.setattr(
            state,
            "spawn_run_process",
            lambda run_id, child_id: spawned_runs.append((run_id, child_id)),
        )

        response = restart(RestartRequest(run_id=child_run_id), state)

        assert response == {"ok": True}
        assert scheduled_events == []
        assert spawned_runs == [(parent_run_id, child_run_id)]
        assert parent_run.status == "finished"
        assert parent_run_id not in state.runner_event_queues
    finally:
        _cleanup(project_id, child_run_id, parent_run_id)


def test_restart_running_parent_without_queue_spawns_directly(monkeypatch):
    project_id = str(uuid.uuid4())
    parent_run_id = str(uuid.uuid4())
    child_run_id = str(uuid.uuid4())
    state = ServerState()

    _seed_run(parent_run_id, project_id)
    _seed_run(child_run_id, project_id, parent_run_id=parent_run_id)
    try:
        parent_run = state.start_run_attempt(
            parent_run_id,
            project_id=project_id,
            reset_runner_connection=True,
        )
        scheduled_events: list[tuple[str, dict]] = []
        spawned_runs: list[tuple[str, str]] = []

        monkeypatch.setattr(
            state,
            "schedule_runner_event",
            lambda run_id, event: scheduled_events.append((run_id, event)),
        )
        monkeypatch.setattr(
            state,
            "spawn_run_process",
            lambda run_id, child_id: spawned_runs.append((run_id, child_id)),
        )

        response = restart(RestartRequest(run_id=child_run_id), state)

        assert response == {"ok": True}
        assert scheduled_events == []
        assert spawned_runs == [(parent_run_id, child_run_id)]
        assert parent_run.status == "finished"
    finally:
        _cleanup(project_id, child_run_id, parent_run_id)


def test_connected_runner_is_not_swept_from_project_runs():
    project_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    state = ServerState()

    _seed_run(run_id, project_id)
    try:
        run = _make_orphaned_run(state, run_id, project_id)
        run.sse_connected = True

        response = _get_project_runs(project_id, state)

        assert [row["run_id"] for row in response["running"]] == [run_id]
        assert response["finished"] == []
        assert run.status == "running"
        assert run_id in state.runner_event_queues
    finally:
        _cleanup(project_id, run_id)
