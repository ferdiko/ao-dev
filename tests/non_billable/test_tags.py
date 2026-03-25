import os
import uuid
from datetime import datetime, timezone

import pytest

from sovara.server.database_manager import DB


def _create_project() -> str:
    project_id = str(uuid.uuid4())
    DB.upsert_project(project_id, f"project-{project_id[:8]}", "")
    return project_id


def _create_session(project_id: str, name: str) -> str:
    session_id = str(uuid.uuid4())
    DB.add_experiment(
        session_id=session_id,
        name=name,
        timestamp=datetime.now(timezone.utc),
        cwd=os.getcwd(),
        command="test",
        environment={"TEST": "true"},
        parent_session_id=session_id,
        project_id=project_id,
    )
    return session_id


@pytest.fixture
def tag_project():
    project_id = _create_project()
    yield project_id
    DB.delete_project(project_id)


def test_project_tags_are_scoped_per_project():
    project_a = _create_project()
    project_b = _create_project()

    try:
        tag_a = DB.create_project_tag(project_a, "Baseline", "#6F7C8B")
        tag_b = DB.create_project_tag(project_b, "Baseline", "#7E8F6A")

        assert [tag["name"] for tag in DB.get_project_tags(project_a)] == ["Baseline"]
        assert [tag["name"] for tag in DB.get_project_tags(project_b)] == ["Baseline"]
        assert tag_a["tag_id"] != tag_b["tag_id"]
        assert tag_a["color"] == "#6F7C8B"
        assert tag_b["color"] == "#7E8F6A"
    finally:
        DB.delete_project(project_a)
        DB.delete_project(project_b)


def test_create_project_tag_rejects_case_insensitive_duplicates(tag_project):
    DB.create_project_tag(tag_project, "Baseline", "#6F7C8B")

    with pytest.raises(ValueError, match="already exists"):
        DB.create_project_tag(tag_project, "baseline", "#7E8F6A")


def test_replace_run_tags_rejects_tags_from_other_projects(tag_project):
    other_project = _create_project()
    session_id = _create_session(tag_project, "Run scoped")
    other_tag = DB.create_project_tag(other_project, "Foreign", "#6E8B7B")

    try:
        with pytest.raises(ValueError, match="must belong"):
            DB.replace_run_tags(session_id, [other_tag["tag_id"]])
    finally:
        DB.delete_project(other_project)


def test_deleting_a_project_tag_removes_it_from_all_runs(tag_project):
    session_a = _create_session(tag_project, "Run A")
    session_b = _create_session(tag_project, "Run B")
    keep_tag = DB.create_project_tag(tag_project, "Keep", "#7F6A8A")
    delete_tag = DB.create_project_tag(tag_project, "Delete", "#8A6F66")

    DB.replace_run_tags(session_a, [keep_tag["tag_id"], delete_tag["tag_id"]])
    DB.replace_run_tags(session_b, [delete_tag["tag_id"]])

    DB.delete_project_tag(tag_project, delete_tag["tag_id"])

    assert [tag["name"] for tag in DB.get_project_tags(tag_project)] == ["Keep"]
    assert [tag["name"] for tag in DB.get_experiment_detail(session_a)["tags"]] == ["Keep"]
    assert DB.get_experiment_detail(session_b)["tags"] == []


def test_deleting_a_project_removes_tag_catalog_and_assignments():
    project_id = _create_project()
    session_id = _create_session(project_id, "Run tagged")
    tag = DB.create_project_tag(project_id, "Ship", "#6A8C93")
    DB.replace_run_tags(session_id, [tag["tag_id"]])

    DB.delete_project(project_id)

    assert DB.query_one("SELECT COUNT(*) AS count FROM project_tags WHERE project_id=?", (project_id,))["count"] == 0
    assert DB.query_one("SELECT COUNT(*) AS count FROM experiment_tags WHERE session_id=?", (session_id,))["count"] == 0


def test_tag_filters_require_selected_tags_to_be_a_subset(tag_project):
    tag_a = DB.create_project_tag(tag_project, "A", "#6F7C8B")
    tag_b = DB.create_project_tag(tag_project, "B", "#7E8F6A")
    tag_c = DB.create_project_tag(tag_project, "C", "#6E8B7B")

    run_none = _create_session(tag_project, "Run none")
    run_a = _create_session(tag_project, "Run a")
    run_ab = _create_session(tag_project, "Run ab")
    run_bc = _create_session(tag_project, "Run bc")

    DB.replace_run_tags(run_a, [tag_a["tag_id"]])
    DB.replace_run_tags(run_ab, [tag_a["tag_id"], tag_b["tag_id"]])
    DB.replace_run_tags(run_bc, [tag_b["tag_id"], tag_c["tag_id"]])

    rows_a, total_a, _ = DB.get_experiment_table_view(
        project_id=tag_project,
        exclude_ids=[],
        filters={"tag_ids": [tag_a["tag_id"]]},
        sort_key="name",
        sort_dir="asc",
        limit=None,
        offset=0,
    )
    rows_ab, total_ab, _ = DB.get_experiment_table_view(
        project_id=tag_project,
        exclude_ids=[],
        filters={"tag_ids": [tag_a["tag_id"], tag_b["tag_id"]]},
        sort_key="name",
        sort_dir="asc",
        limit=None,
        offset=0,
    )

    assert total_a == 2
    assert {row["session_id"] for row in rows_a} == {run_a, run_ab}
    assert total_ab == 1
    assert [row["session_id"] for row in rows_ab] == [run_ab]
    assert run_none not in {row["session_id"] for row in rows_a}
    assert run_bc not in {row["session_id"] for row in rows_ab}
