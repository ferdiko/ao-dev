import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

import pytest
import sovara.server.routes.ui as ui_module
from fastapi import HTTPException

from sovara.common.constants import PRIORS_SERVER_URL, SOVARA_CONFIG
from sovara.server.database import DB
from sovara.server.routes.ui import (
    CreateProjectTagRequest,
    EditInputRequest,
    EditOutputRequest,
    ChatMessageRequest,
    PersistedTraceChatHistoryRequest,
    RestartRequest,
    UpdateUserLlmSettingsRequest,
    UpdateUserLlmTierSettingsRequest,
    abort_trace_chat,
    chat,
    clear_trace_chat_history,
    create_project_tag,
    edit_input,
    edit_output,
    get_user,
    get_trace_chat_history,
    get_project_runs,
    get_ui_config,
    restart,
    update_user_llm_settings,
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


def test_get_user_includes_default_llm_settings(monkeypatch):
    user_id = str(uuid.uuid4())
    DB.upsert_user(user_id, "User One", "user@example.com")
    monkeypatch.setattr(ui_module, "read_user_id", lambda: user_id)

    try:
        response = get_user()
    finally:
        DB.delete_user(user_id)

    assert response == {
        "user": {
            "user_id": user_id,
            "full_name": "User One",
            "email": "user@example.com",
            "llm_settings": {
                "primary": {
                    "provider": "together",
                    "model_name": "Qwen/Qwen3.5-397B-A17B",
                    "api_base": None,
                },
                "helper": {
                    "provider": "together",
                    "model_name": "Qwen/Qwen3.5-9B",
                    "api_base": None,
                },
            },
        },
    }


def test_update_user_llm_settings_round_trips(monkeypatch):
    user_id = str(uuid.uuid4())
    state = ServerState()
    DB.upsert_user(user_id, "User One", "user@example.com")
    monkeypatch.setattr(ui_module, "read_user_id", lambda: user_id)

    try:
        response = update_user_llm_settings(
            UpdateUserLlmSettingsRequest(
                primary=UpdateUserLlmTierSettingsRequest(
                    provider="hosted_vllm",
                    model_name="Meta-Llama-3.1-70B-Instruct",
                    api_base="http://192.168.1.50:8000/v1",
                ),
                helper=UpdateUserLlmTierSettingsRequest(
                    provider="anthropic",
                    model_name="claude-haiku-4-5",
                ),
            ),
            state,
        )
        row = DB.get_user(user_id)
    finally:
        DB.delete_user(user_id)

    assert response == {
        "user": {
            "user_id": user_id,
            "full_name": "User One",
            "email": "user@example.com",
            "llm_settings": {
                "primary": {
                    "provider": "hosted_vllm",
                    "model_name": "Meta-Llama-3.1-70B-Instruct",
                    "api_base": "http://192.168.1.50:8000/v1",
                },
                "helper": {
                    "provider": "anthropic",
                    "model_name": "claude-haiku-4-5",
                    "api_base": None,
                },
            },
        },
    }
    assert row["llm_primary_provider"] == "hosted_vllm"
    assert row["llm_primary_model_name"] == "Meta-Llama-3.1-70B-Instruct"
    assert row["llm_primary_api_base"] == "http://192.168.1.50:8000/v1"
    assert row["llm_helper_provider"] == "anthropic"
    assert row["llm_helper_model_name"] == "claude-haiku-4-5"
    assert row["llm_helper_api_base"] is None


def test_update_user_llm_settings_requires_hosted_vllm_api_base(monkeypatch):
    user_id = str(uuid.uuid4())
    state = ServerState()
    DB.upsert_user(user_id, "User One", "user@example.com")
    monkeypatch.setattr(ui_module, "read_user_id", lambda: user_id)

    try:
        response = update_user_llm_settings(
            UpdateUserLlmSettingsRequest(
                primary=UpdateUserLlmTierSettingsRequest(
                    provider="hosted_vllm",
                    model_name="Meta-Llama-3.1-70B-Instruct",
                    api_base="",
                ),
                helper=UpdateUserLlmTierSettingsRequest(
                    provider="together",
                    model_name="Qwen/Qwen3.5-9B",
                ),
            ),
            state,
        )
    finally:
        DB.delete_user(user_id)

    assert response.status_code == 400
    assert _response_json(response) == {
        "error": "Primary API base is required for hosted vLLM.",
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
    state = ServerState()
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
            state,
        )

        assert response == {
            "answer": "done",
            "edits_applied": False,
            "history": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "done"},
            ],
        }
        assert DB.get_trace_chat_history(run_id) == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "done"},
        ]
    finally:
        DB.delete_project(project_id)


@pytest.mark.anyio
async def test_chat_route_drops_cancelled_completion(monkeypatch):
    import httpx

    project_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    state = ServerState()
    DB.upsert_project(project_id, "trace-chat-project", "")
    started = asyncio.Event()
    release = asyncio.Event()

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"answer": "done", "edits_applied": False}

    class FakeAbortResponse:
        status_code = 202

        @staticmethod
        def json():
            return {"status": "cancelling"}

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, timeout=None):
            if url.endswith("/abort"):
                return FakeAbortResponse()
            started.set()
            await release.wait()
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

        task = asyncio.create_task(chat(run_id, ChatMessageRequest(message="hello", history=[]), state))
        await started.wait()

        assert await abort_trace_chat(run_id, state) == {"status": "cancelling"}
        release.set()

        with pytest.raises(HTTPException) as exc:
            await task

        assert exc.value.status_code == 409
        assert DB.get_trace_chat_history(run_id) == [
            {"role": "user", "content": "hello"},
        ]
    finally:
        DB.delete_project(project_id)


@pytest.mark.anyio
async def test_chat_route_drops_stale_completion_after_newer_request(monkeypatch):
    import httpx

    project_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    state = ServerState()
    DB.upsert_project(project_id, "trace-chat-project", "")
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    class FakeResponse:
        def __init__(self, answer: str):
            self.status_code = 200
            self._answer = answer

        def json(self):
            return {"answer": self._answer, "edits_applied": False}

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, timeout=None):
            if json and json.get("message") == "first":
                first_started.set()
                await release_first.wait()
                return FakeResponse("old answer")
            return FakeResponse("new answer")

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

        first_task = asyncio.create_task(chat(run_id, ChatMessageRequest(message="first", history=[]), state))
        await first_started.wait()

        second_response = await chat(
            run_id,
            ChatMessageRequest(
                message="second",
                history=[{"role": "user", "content": "first"}],
            ),
            state,
        )

        assert second_response == {
            "answer": "new answer",
            "edits_applied": False,
            "history": [
                {"role": "user", "content": "first"},
                {"role": "user", "content": "second"},
                {"role": "assistant", "content": "new answer"},
            ],
        }

        release_first.set()
        with pytest.raises(HTTPException) as exc:
            await first_task

        assert exc.value.status_code == 409
        assert DB.get_trace_chat_history(run_id) == [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "new answer"},
        ]
    finally:
        DB.delete_project(project_id)
