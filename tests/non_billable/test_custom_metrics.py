import os
import threading
import uuid
import warnings
from datetime import datetime, timezone

import pytest

from sovara.common.custom_metrics import MetricsPayload
from sovara.server.database import DB
from sovara.server.handlers.runner_handlers import handle_add_node
from sovara.server.state import ServerState


def _create_run(project_id: str) -> str:
    run_id = str(uuid.uuid4())
    DB.add_run(
        run_id=run_id,
        name=f"Run {run_id[:8]}",
        timestamp=datetime.now(timezone.utc),
        cwd=os.getcwd(),
        command="test",
        environment={"TEST": "true"},
        parent_run_id=run_id,
        project_id=project_id,
    )
    return run_id


@pytest.fixture
def metric_project():
    project_id = str(uuid.uuid4())
    DB.upsert_project(project_id, f"project-{project_id[:8]}", "")
    yield project_id
    DB.execute("DELETE FROM runs WHERE project_id=?", (project_id,))
    DB.execute("DELETE FROM project_metric_kinds WHERE project_id=?", (project_id,))
    DB.execute("DELETE FROM projects WHERE project_id=?", (project_id,))


def test_metrics_payload_requires_nonempty_snake_case_metrics():
    with pytest.raises(ValueError, match="at least one metric"):
        MetricsPayload(metrics={})

    with pytest.raises(ValueError, match="lower_snake_case"):
        MetricsPayload(metrics={"Bad-Key": 1})

    payload = MetricsPayload(metrics={"confidence": 0.95, "is_correct": True, "n_correct": 12})
    assert payload.metrics == {"confidence": 0.95, "is_correct": True, "n_correct": 12}


def test_add_metrics_rejects_duplicate_metric_keys_within_run(metric_project):
    run_id = _create_run(metric_project)

    DB.add_metrics(run_id, {"confidence": 0.7})

    with pytest.raises(ValueError, match="already logged"):
        DB.add_metrics(run_id, {"confidence": 0.9})


def test_add_metrics_rejects_kind_conflicts_within_project(metric_project):
    run_a = _create_run(metric_project)
    run_b = _create_run(metric_project)

    DB.add_metrics(run_a, {"success": True})

    with pytest.raises(ValueError, match="already registered as kind 'bool'"):
        DB.add_metrics(run_b, {"success": 1})


def test_experiment_timestamp_writes_do_not_emit_sqlite_datetime_warning(metric_project):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        run_id = _create_run(metric_project)
        DB.update_timestamp(run_id, datetime.now(timezone.utc))

    messages = [
        str(warning.message)
        for warning in caught
        if issubclass(warning.category, DeprecationWarning)
    ]
    assert all("default datetime adapter" not in message for message in messages)


def test_runtime_checkpoint_and_finalize_persist_expected_fields(metric_project):
    run_id = _create_run(metric_project)

    DB.update_active_runtime_seconds(run_id, 4.2)
    row = DB.get_run_detail(run_id)
    assert row["runtime_seconds"] is None
    assert row["active_runtime_seconds"] == pytest.approx(4.2)

    DB.finalize_runtime(run_id, 9.8)
    row = DB.get_run_detail(run_id)
    assert row["runtime_seconds"] == pytest.approx(9.8)
    assert row["active_runtime_seconds"] is None


def test_runtime_finalize_preserves_first_canonical_runtime_across_reruns(metric_project):
    run_id = _create_run(metric_project)

    DB.finalize_runtime(run_id, 18.6)
    DB.update_active_runtime_seconds(run_id, 2.4)
    DB.finalize_runtime(run_id, 2.4)

    row = DB.get_run_detail(run_id)
    assert row["runtime_seconds"] == pytest.approx(18.6)
    assert row["active_runtime_seconds"] is None


def test_add_node_runtime_checkpoint_does_not_deadlock(metric_project):
    run_id = _create_run(metric_project)
    state = ServerState()
    state.start_run_attempt(run_id, project_id=metric_project)

    node_message = {
        "run_id": run_id,
        "node": {
            "uuid": "node-1",
            "input": "{}",
            "output": "{}",
            "label": "Node 1",
            "border_color": "#43884e",
        },
        "incoming_edges": [],
    }

    worker = threading.Thread(
        target=handle_add_node,
        args=(state, node_message),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=1.0)

    assert not worker.is_alive(), "handle_add_node deadlocked while checkpointing runtime"
