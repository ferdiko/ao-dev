import json
import os
import uuid
from datetime import datetime, timezone

import pytest

from sovara.common.constants import PRIORS_SERVER_URL, SOVARA_CONFIG
from sovara.server.database_manager import DB
from sovara.server.routes.ui import (
    CreateProjectTagRequest,
    EditInputRequest,
    EditOutputRequest,
    ChatMessageRequest,
    PersistedTraceChatHistoryRequest,
    RestartRequest,
    chat,
    clear_trace_chat_history,
    create_project_tag,
    edit_input,
    edit_output,
    get_trace_chat_history,
    get_project_runs,
    get_ui_config,
    restart,
    update_trace_chat_history,
)
from sovara.server.state import ServerState


def _response_json(response) -> dict:
    return json.loads(response.body)


def test_restart_missing_run_returns_404():
    missing_run_id = str(uuid.uuid4())
    state = ServerState()

    response = restart(RestartRequest(run_id=missing_run_id), state)

    assert response.status_code == 404
    assert _response_json(response) == {"error": f"Run not found: {missing_run_id}"}


def test_edit_input_missing_node_returns_404():
    run_id = str(uuid.uuid4())
    node_uuid = "missing-node"
    state = ServerState()

    response = edit_input(
        EditInputRequest(run_id=run_id, node_uuid=node_uuid, value="{}"),
        state,
    )

    assert response.status_code == 404
    assert _response_json(response) == {
        "error": f"Input node not found for run_id={run_id}, node_uuid={node_uuid}.",
    }


def test_edit_input_invalid_json_returns_400():
    run_id = str(uuid.uuid4())
    node_uuid = "missing-node"
    state = ServerState()

    response = edit_input(
        EditInputRequest(run_id=run_id, node_uuid=node_uuid, value="{"),
        state,
    )

    assert response.status_code == 400
    assert _response_json(response) == {
        "error": f"Invalid input JSON for run_id={run_id}, node_uuid={node_uuid}: Expecting property name enclosed in double quotes.",
    }


def test_edit_output_missing_node_returns_404():
    run_id = str(uuid.uuid4())
    node_uuid = "missing-node"
    state = ServerState()

    response = edit_output(
        EditOutputRequest(run_id=run_id, node_uuid=node_uuid, value="{}"),
        state,
    )

    assert response.status_code == 404
    assert _response_json(response) == {
        "error": f"Output node not found for run_id={run_id}, node_uuid={node_uuid}.",
    }


def test_edit_output_invalid_json_returns_400():
    run_id = str(uuid.uuid4())
    node_uuid = "missing-node"
    state = ServerState()

    response = edit_output(
        EditOutputRequest(run_id=run_id, node_uuid=node_uuid, value="{"),
        state,
    )

    assert response.status_code == 400
    assert _response_json(response) == {
        "error": f"Invalid output JSON for run_id={run_id}, node_uuid={node_uuid}: Expecting property name enclosed in double quotes.",
    }


def test_create_project_tag_accepts_github_palette_colors():
    project_id = str(uuid.uuid4())
    state = ServerState()
    DB.upsert_project(project_id, "test-project", "")

    try:
        response = create_project_tag(
            project_id,
            CreateProjectTagRequest(name="Ship", color="#1a7f37"),
            state,
        )
    finally:
        DB.delete_project(project_id)

    assert response == {
        "tag": {
            "tag_id": response["tag"]["tag_id"],
            "name": "Ship",
            "color": "#1a7f37",
        },
    }


def test_get_ui_config_returns_bootstrap_values():
    assert get_ui_config() == {
        "config_path": SOVARA_CONFIG,
        "priors_url": PRIORS_SERVER_URL,
    }


def test_get_project_runs_applies_bool_metric_filters():
    project_id = str(uuid.uuid4())
    state = ServerState()
    DB.upsert_project(project_id, "metric-project", "")

    run_true = str(uuid.uuid4())
    run_false = str(uuid.uuid4())

    try:
        for run_id, name in ((run_true, "Run true"), (run_false, "Run false")):
            DB.add_run(
                run_id=run_id,
                name=name,
                timestamp=datetime.now(timezone.utc),
                cwd=os.getcwd(),
                command="test",
                environment={},
                parent_run_id=run_id,
                project_id=project_id,
            )
            DB.update_runtime_seconds(run_id, 2.5)

        DB.add_metrics(run_true, {"success": True})
        DB.add_metrics(run_false, {"success": False})

        response = get_project_runs(
            project_id=project_id,
            label=[],
            tag_id=[],
            version=[],
            metric_filters='{"success":{"kind":"bool","values":[true]}}',
            state=state,
        )

        assert [row["run_id"] for row in response["finished"]] == [run_true]
    finally:
        DB.delete_project(project_id)


def test_trace_chat_history_round_trips_for_a_run():
    project_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    DB.upsert_project(project_id, "trace-chat-project", "")

    try:
        DB.add_run(
            run_id=run_id,
            name="Trace Chat Run",
            timestamp=datetime.now(timezone.utc),
            cwd=os.getcwd(),
            command="test",
            environment={},
            parent_run_id=run_id,
            project_id=project_id,
        )

        update_response = update_trace_chat_history(
            run_id,
            PersistedTraceChatHistoryRequest(history=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ]),
        )
        get_response = get_trace_chat_history(run_id)
        clear_response = clear_trace_chat_history(run_id)

        assert update_response == {
            "history": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ],
        }
        assert get_response == update_response
        assert clear_response == {"history": []}
        assert get_trace_chat_history(run_id) == {"history": []}
    finally:
        DB.delete_project(project_id)


def test_trace_chat_history_invalid_json_falls_back_to_empty_history():
    project_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    DB.upsert_project(project_id, "trace-chat-project", "")

    try:
        DB.add_run(
            run_id=run_id,
            name="Trace Chat Run",
            timestamp=datetime.now(timezone.utc),
            cwd=os.getcwd(),
            command="test",
            environment={},
            parent_run_id=run_id,
            project_id=project_id,
        )
        DB.execute("UPDATE runs SET trace_chat_history=? WHERE run_id=?", ("{", run_id))

        assert get_trace_chat_history(run_id) == {"history": []}
    finally:
        DB.delete_project(project_id)


@pytest.mark.anyio
async def test_chat_route_persists_user_message_before_proxy_and_appends_answer(monkeypatch):
    import httpx

    project_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    DB.upsert_project(project_id, "trace-chat-project", "")

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"answer": "done", "edits_applied": False}

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, timeout):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    try:
        DB.add_run(
            run_id=run_id,
            name="Trace Chat Run",
            timestamp=datetime.now(timezone.utc),
            cwd=os.getcwd(),
            command="test",
            environment={},
            parent_run_id=run_id,
            project_id=project_id,
        )

        response = await chat(
            run_id,
            ChatMessageRequest(message="hello", history=[]),
        )

        assert response == {"answer": "done", "edits_applied": False}
        assert DB.get_trace_chat_history(run_id) == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "done"},
        ]
    finally:
        DB.delete_project(project_id)
