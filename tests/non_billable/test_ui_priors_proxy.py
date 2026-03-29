import os
import uuid
from datetime import datetime, timezone

from sovara.common.constants import TEST_PROJECT_ID, TEST_USER_ID
from sovara.server.database_manager import DB
from sovara.server.graph_models import GraphNode, RunGraph
from sovara.server.priors_client import PriorsBackendError
from sovara.server.routes import ui
from sovara.server.routes.ui import (
    UiFolderCreateRequest,
    UiFolderDeleteRequest,
    UiFolderLsRequest,
    UiFolderMoveRequest,
    UiPriorCreateRequest,
    UiPriorItemRef,
    UiPriorItemsCopyRequest,
    UiPriorItemsDeleteRequest,
    UiPriorItemsMoveRequest,
    UiPriorSubmitRequest,
    UiPriorUpdateRequest,
)
from sovara.server.state import ServerState


class _FakePriorsClient:
    def __init__(self):
        self.calls = []

    def list_priors(self, *, path=None):
        self.calls.append(("list_priors", path))
        return {"priors": [{"id": "p1"}]}

    def create_prior(self, body, *, force=False):
        self.calls.append(("create_prior", body, force))
        return {"status": "created", "id": "p1"}

    def create_draft_prior(self, body):
        self.calls.append(("create_draft_prior", body))
        return {"status": "created", "id": "p-draft", "prior_status": "draft"}

    def update_prior(self, prior_id, body, *, force=False):
        self.calls.append(("update_prior", prior_id, body, force))
        return {"status": "updated", "id": prior_id}

    def submit_prior(self, prior_id, body, *, force=False):
        self.calls.append(("submit_prior", prior_id, body, force))
        return {"status": "submitted", "id": prior_id, "prior_status": "active"}

    def delete_prior(self, prior_id):
        self.calls.append(("delete_prior", prior_id))
        return {"status": "deleted", "id": prior_id}

    def folder_ls(self, path):
        self.calls.append(("folder_ls", path))
        return {"path": path, "folders": [], "priors": [], "prior_count": 0}

    def create_folder(self, path):
        self.calls.append(("create_folder", path))
        return {"status": "created", "path": path}

    def move_folder(self, path, new_path):
        self.calls.append(("move_folder", path, new_path))
        return {"status": "updated", "path": path, "new_path": new_path}

    def delete_folder(self, path):
        self.calls.append(("delete_folder", path))
        return {"status": "deleted", "path": path}

    def copy_items(self, items, destination_path, *, as_draft=False):
        self.calls.append(("copy_items", items, destination_path, as_draft))
        return {"status": "copied", "items": items, "count": len(items)}

    def move_items(self, items, destination_path):
        self.calls.append(("move_items", items, destination_path))
        return {"status": "moved", "items": items, "count": len(items)}

    def delete_items(self, items):
        self.calls.append(("delete_items", items))
        return {"status": "deleted", "count": len(items)}


def test_resolve_active_priors_scope_prefers_workspace_project(monkeypatch):
    monkeypatch.setattr(ui, "read_user_id", lambda: "user-1")
    monkeypatch.setenv("SOVARA_WORKSPACE_ROOT", "/tmp/workspace")
    monkeypatch.setattr(ui, "find_project_root", lambda workspace_root: "/tmp/workspace")
    monkeypatch.setattr(ui, "read_project_id", lambda project_root: "project-1")

    assert ui._resolve_active_priors_scope() == ("user-1", "project-1")


def test_resolve_active_priors_scope_accepts_explicit_project_override(monkeypatch):
    monkeypatch.setattr(ui, "read_user_id", lambda: "user-1")
    monkeypatch.setattr(ui.DB, "get_project", lambda project_id: {"project_id": project_id} if project_id == "project-2" else None)

    assert ui._resolve_active_priors_scope(project_id="project-2") == ("user-1", "project-2")


def test_list_priors_proxy_uses_backend_client(monkeypatch):
    client = _FakePriorsClient()
    seen_project_ids = []
    monkeypatch.setattr(
        ui,
        "_get_priors_backend_client",
        lambda project_id=None: (seen_project_ids.append(project_id), client)[1],
    )

    result = ui.list_priors(path="demo/", project_id="project-2")

    assert result == {"priors": [{"id": "p1"}]}
    assert seen_project_ids == ["project-2"]
    assert client.calls == [("list_priors", "demo/")]


def test_create_prior_proxy_broadcasts_refresh(monkeypatch):
    client = _FakePriorsClient()
    seen_project_ids = []
    monkeypatch.setattr(
        ui,
        "_get_priors_backend_client",
        lambda project_id=None: (seen_project_ids.append(project_id), client)[1],
    )
    state = ServerState()
    broadcasts = []
    monkeypatch.setattr(state, "schedule_broadcast", lambda msg: broadcasts.append(msg))

    result = ui.create_prior(
        UiPriorCreateRequest(name="Retry", summary="Use retries", content="Retry failures", path="ops/"),
        force=False,
        project_id="project-2",
        state=state,
    )

    assert result == {"status": "created", "id": "p1"}
    assert seen_project_ids == ["project-2"]
    assert broadcasts == [{"type": "priors_refresh"}]
    assert client.calls[0][0] == "create_prior"


def test_create_draft_and_submit_prior_proxy_broadcast_refresh(monkeypatch):
    client = _FakePriorsClient()
    monkeypatch.setattr(ui, "_get_priors_backend_client", lambda project_id=None: client)
    state = ServerState()
    broadcasts = []
    monkeypatch.setattr(state, "schedule_broadcast", lambda msg: broadcasts.append(msg))

    draft_result = ui.create_prior_draft(
        UiPriorCreateRequest(name="Draft", content="Draft content", path="ops/"),
        project_id="project-2",
        state=state,
    )
    submit_result = ui.submit_prior(
        "p-draft",
        UiPriorSubmitRequest(content="Final content"),
        force=False,
        project_id="project-2",
        state=state,
    )

    assert draft_result == {"status": "created", "id": "p-draft", "prior_status": "draft"}
    assert submit_result == {"status": "submitted", "id": "p-draft", "prior_status": "active"}
    assert broadcasts == [{"type": "priors_refresh"}, {"type": "priors_refresh"}]
    assert client.calls == [
        ("create_draft_prior", {"name": "Draft", "summary": None, "content": "Draft content", "path": "ops/", "creation_trace_id": None, "trace_source": None}),
        ("submit_prior", "p-draft", {"content": "Final content"}, False),
    ]


def test_update_and_delete_prior_proxy_broadcast_refresh(monkeypatch):
    client = _FakePriorsClient()
    seen_project_ids = []
    monkeypatch.setattr(
        ui,
        "_get_priors_backend_client",
        lambda project_id=None: (seen_project_ids.append(project_id), client)[1],
    )
    state = ServerState()
    broadcasts = []
    monkeypatch.setattr(state, "schedule_broadcast", lambda msg: broadcasts.append(msg))

    update_result = ui.update_prior(
        "p1",
        UiPriorUpdateRequest(content="Updated"),
        force=True,
        project_id="project-2",
        state=state,
    )
    delete_result = ui.delete_prior("p1", project_id="project-2", state=state)

    assert update_result == {"status": "updated", "id": "p1"}
    assert delete_result == {"status": "deleted", "id": "p1"}
    assert seen_project_ids == ["project-2", "project-2"]
    assert broadcasts == [{"type": "priors_refresh"}, {"type": "priors_refresh"}]


def test_folder_mutation_proxies_broadcast_refresh(monkeypatch):
    client = _FakePriorsClient()
    seen_project_ids = []
    monkeypatch.setattr(
        ui,
        "_get_priors_backend_client",
        lambda project_id=None: (seen_project_ids.append(project_id), client)[1],
    )
    state = ServerState()
    broadcasts = []
    monkeypatch.setattr(state, "schedule_broadcast", lambda msg: broadcasts.append(msg))

    create_result = ui.create_folder(
        UiFolderCreateRequest(path="ops/"),
        project_id="project-2",
        state=state,
    )
    move_result = ui.move_folder(
        UiFolderMoveRequest(path="ops/", new_path="platform/"),
        project_id="project-2",
        state=state,
    )
    delete_result = ui.delete_folder(
        UiFolderDeleteRequest(path="platform/"),
        project_id="project-2",
        state=state,
    )

    assert create_result == {"status": "created", "path": "ops/"}
    assert move_result == {"status": "updated", "path": "ops/", "new_path": "platform/"}
    assert delete_result == {"status": "deleted", "path": "platform/"}
    assert seen_project_ids == ["project-2", "project-2", "project-2"]
    assert broadcasts == [{"type": "priors_refresh"}, {"type": "priors_refresh"}, {"type": "priors_refresh"}]


def test_prior_item_mutation_proxies_broadcast_refresh(monkeypatch):
    client = _FakePriorsClient()
    seen_project_ids = []
    monkeypatch.setattr(
        ui,
        "_get_priors_backend_client",
        lambda project_id=None: (seen_project_ids.append(project_id), client)[1],
    )
    state = ServerState()
    broadcasts = []
    monkeypatch.setattr(state, "schedule_broadcast", lambda msg: broadcasts.append(msg))

    items = [
        UiPriorItemRef(kind="prior", id="p1"),
        UiPriorItemRef(kind="folder", path="ops/"),
    ]
    copy_result = ui.copy_prior_items(
        UiPriorItemsCopyRequest(items=items, destination_path="library/", as_draft=True),
        project_id="project-2",
        state=state,
    )
    move_result = ui.move_prior_items(
        UiPriorItemsMoveRequest(items=items, destination_path="library/"),
        project_id="project-2",
        state=state,
    )
    delete_result = ui.delete_prior_items(
        UiPriorItemsDeleteRequest(items=items),
        project_id="project-2",
        state=state,
    )

    assert copy_result == {
        "status": "copied",
        "items": [{"kind": "prior", "id": "p1"}, {"kind": "folder", "path": "ops/"}],
        "count": 2,
    }
    assert move_result == {
        "status": "moved",
        "items": [{"kind": "prior", "id": "p1"}, {"kind": "folder", "path": "ops/"}],
        "count": 2,
    }
    assert delete_result == {"status": "deleted", "count": 2}
    assert seen_project_ids == ["project-2", "project-2", "project-2"]
    assert broadcasts == [{"type": "priors_refresh"}, {"type": "priors_refresh"}, {"type": "priors_refresh"}]
    assert client.calls[0] == ("copy_items", [{"kind": "prior", "id": "p1"}, {"kind": "folder", "path": "ops/"}], "library/", True)


def test_priors_proxy_maps_backend_error(monkeypatch):
    class _FailingClient:
        def folder_ls(self, path):
            raise PriorsBackendError("locked", status_code=423)

    monkeypatch.setattr(ui, "_get_priors_backend_client", lambda project_id=None: _FailingClient())

    response = ui.folder_ls(UiFolderLsRequest(path="ops/"), project_id="project-2")

    assert response.status_code == 423
    assert response.body == b'{"error":"locked"}'


def _seed_run(run_id: str) -> None:
    DB.add_run(
        run_id=run_id,
        name="UI Priors",
        timestamp=datetime.now(timezone.utc),
        cwd="/tmp",
        command="python -m workflow",
        environment={},
        project_id=TEST_PROJECT_ID,
        user_id=TEST_USER_ID,
    )


def test_get_graph_enriches_nodes_with_prior_metadata():
    run_id = str(uuid.uuid4())
    node_uuid = str(uuid.uuid4())
    state = ServerState()
    _seed_run(run_id)

    try:
        DB.update_graph_topology(
            run_id,
            RunGraph(
                nodes=[
                    GraphNode(
                        uuid=node_uuid,
                        step_id=1,
                        input="{}",
                        output="{}",
                        label="OpenAI",
                        border_color="#000000",
                    )
                ],
                edges=[],
            ),
        )
        DB.upsert_prior_retrieval(
            run_id,
            node_uuid,
            status="timeout",
            applied_priors=[],
            timeout_ms=30000,
            error_message="timed out",
        )

        result = ui.get_graph(run_id, state=state)

        assert result["payload"]["nodes"][0]["prior_status"] == "timeout"
        assert result["payload"]["nodes"][0]["prior_count"] == 0
    finally:
        DB.backend.delete_runs_by_ids_query([run_id], user_id=None)


def test_get_node_prior_retrieval_returns_lazy_record():
    run_id = str(uuid.uuid4())
    node_uuid = str(uuid.uuid4())
    _seed_run(run_id)

    try:
        DB.backend.insert_llm_call_with_output_query(
            run_id,
            '{"raw":{"body":{}},"to_show":{"body":{"instructions":"hello"}}}',
            "hash-ui-priors",
            node_uuid,
            "httpx.Client.send",
            '{"raw":{"content":"ok"},"to_show":{"content":"ok"}}',
            "stack line",
            "llm",
            "[]",
        )
        DB.upsert_prior_retrieval(
            run_id,
            node_uuid,
            status="applied",
            retrieval_context="body.instructions: hello",
            applied_priors=[{"id": "p1", "content": "Retry once"}],
            rendered_priors_block="<sovara-priors>...</sovara-priors>",
        )

        result = ui.get_node_prior_retrieval(run_id, node_uuid)

        assert result["type"] == "prior_retrieval"
        assert result["record"]["status"] == "applied"
        assert result["record"]["applied_priors"] == [{"id": "p1", "content": "Retry once"}]
    finally:
        DB.backend.delete_runs_by_ids_query([run_id], user_id=None)
