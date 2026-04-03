import os
import uuid
from datetime import datetime, timezone

from sovara.server.database import DB


def _create_project() -> str:
    project_id = str(uuid.uuid4())
    DB.upsert_project(project_id, f"project-{project_id[:8]}", "")
    return project_id


def _create_run(
    project_id: str,
    name: str,
    *,
    runtime_seconds: float | None = None,
    active_runtime_seconds: float | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    DB.add_run(
        run_id=run_id,
        name=name,
        timestamp=datetime.now(timezone.utc),
        cwd=os.getcwd(),
        command="test",
        environment={"TEST": "true"},
        parent_run_id=run_id,
        project_id=project_id,
    )
    if runtime_seconds is not None:
        DB.update_runtime_seconds(run_id, runtime_seconds)
    if active_runtime_seconds is not None:
        DB.update_active_runtime_seconds(run_id, active_runtime_seconds)
    return run_id


def test_latency_filters_match_runtime_and_active_runtime_values():
    project_id = _create_project()

    try:
        outside_low = _create_run(project_id, "Run low", runtime_seconds=1.1)
        matching_active = _create_run(project_id, "Run active", active_runtime_seconds=4.2)
        matching_finished = _create_run(project_id, "Run finished", runtime_seconds=4.8)
        outside_high = _create_run(project_id, "Run high", runtime_seconds=9.3)
        missing_runtime = _create_run(project_id, "Run none")

        rows, total, _ = DB.get_run_table_view(
            project_id=project_id,
            exclude_ids=[],
            filters={"latency_min": 4.0, "latency_max": 5.0},
            sort_key="name",
            sort_dir="asc",
            limit=None,
            offset=0,
        )

        assert total == 2
        assert [row["run_id"] for row in rows] == [matching_active, matching_finished]
        assert outside_low not in {row["run_id"] for row in rows}
        assert outside_high not in {row["run_id"] for row in rows}
        assert missing_runtime not in {row["run_id"] for row in rows}
    finally:
        DB.delete_project(project_id)


def test_bool_custom_metric_filters_match_success_values():
    project_id = _create_project()

    try:
        run_success = _create_run(project_id, "Run success", runtime_seconds=3.2)
        run_failure = _create_run(project_id, "Run failure", runtime_seconds=4.4)
        run_missing = _create_run(project_id, "Run missing", runtime_seconds=5.6)

        DB.add_metrics(run_success, {"success": True})
        DB.add_metrics(run_failure, {"success": False})

        rows, total, _ = DB.get_run_table_view(
            project_id=project_id,
            exclude_ids=[],
            filters={"custom_metrics": {"success": {"kind": "bool", "values": [True]}}},
            sort_key="name",
            sort_dir="asc",
            limit=None,
            offset=0,
        )

        assert total == 1
        assert [row["run_id"] for row in rows] == [run_success]
        assert run_failure not in {row["run_id"] for row in rows}
        assert run_missing not in {row["run_id"] for row in rows}
    finally:
        DB.delete_project(project_id)
