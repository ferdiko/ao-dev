import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sovara.common.constants import TEST_PROJECT_ID, TEST_USER_ID
from sovara.server import llm_backend
from sovara.server.database_manager import DB
from sovara.server.llm_backend import StructuredInferenceError
from sovara.server.routes.internal import router as internal_router


def _response_with_text(text: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
            )
        ]
    )


_SIMPLE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "test_payload",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
            },
            "required": ["answer"],
            "additionalProperties": False,
        },
    },
}


def test_infer_structured_json_uses_native_path_when_response_is_valid(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_backend, "_supports_native_response_format", lambda model, response_format: True)

    def fake_infer(messages, model, tier="expensive", **kwargs):
        calls.append(
            {
                "messages": messages,
                "model": model,
                "tier": tier,
                "kwargs": kwargs,
            }
        )
        return _response_with_text('{"answer":"native"}')

    monkeypatch.setattr(llm_backend, "infer", fake_infer)

    result = llm_backend.infer_structured_json(
        [{"role": "user", "content": "hello"}],
        "openai/gpt-5.4",
        tier="cheap",
        response_format=_SIMPLE_RESPONSE_FORMAT,
    )

    assert result == {
        "raw_text": '{"answer":"native"}',
        "parsed": {"answer": "native"},
        "structured_mode": "native",
        "model_used": "openai/gpt-5.4-mini",
    }
    assert len(calls) == 1
    assert calls[0]["kwargs"]["response_format"] == _SIMPLE_RESPONSE_FORMAT


def test_infer_structured_json_falls_back_to_local_parse_when_native_path_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_backend, "_supports_native_response_format", lambda model, response_format: True)

    def fake_infer(messages, model, tier="expensive", **kwargs):
        calls.append(
            {
                "messages": messages,
                "model": model,
                "tier": tier,
                "kwargs": kwargs,
            }
        )
        if len(calls) == 1:
            raise RuntimeError("backend does not support response_format")
        return _response_with_text('{"answer":"fallback"}')

    monkeypatch.setattr(llm_backend, "infer", fake_infer)

    result = llm_backend.infer_structured_json(
        [{"role": "user", "content": "hello"}],
        "openai/gpt-5.4",
        response_format=_SIMPLE_RESPONSE_FORMAT,
        repair_attempts=0,
    )

    assert result == {
        "raw_text": '{"answer":"fallback"}',
        "parsed": {"answer": "fallback"},
        "structured_mode": "local_parse",
        "model_used": "openai/gpt-5.4",
    }
    assert len(calls) == 2
    assert calls[0]["kwargs"]["response_format"] == _SIMPLE_RESPONSE_FORMAT
    assert "response_format" not in calls[1]["kwargs"]
    assert calls[1]["messages"][0]["role"] == "system"
    assert "Return ONLY valid JSON" in calls[1]["messages"][0]["content"]


def test_infer_structured_json_repairs_invalid_fallback_json(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_backend, "_supports_native_response_format", lambda model, response_format: True)

    def fake_infer(messages, model, tier="expensive", **kwargs):
        calls.append(
            {
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        if len(calls) == 1:
            raise RuntimeError("native mode unavailable")
        if len(calls) == 2:
            return _response_with_text("not json")
        return _response_with_text('{"answer":"repaired"}')

    monkeypatch.setattr(llm_backend, "infer", fake_infer)

    result = llm_backend.infer_structured_json(
        [{"role": "user", "content": "hello"}],
        "openai/gpt-5.4",
        response_format=_SIMPLE_RESPONSE_FORMAT,
        repair_attempts=1,
    )

    assert result == {
        "raw_text": '{"answer":"repaired"}',
        "parsed": {"answer": "repaired"},
        "structured_mode": "retry_repaired",
        "model_used": "openai/gpt-5.4",
    }
    assert len(calls) == 3
    repair_messages = calls[2]["messages"]
    assert repair_messages[-2]["role"] == "assistant"
    assert repair_messages[-2]["content"] == "not json"
    assert repair_messages[-1]["role"] == "user"
    assert "did not validate" in repair_messages[-1]["content"]


def test_infer_structured_json_raises_after_invalid_repair_attempts(monkeypatch):
    monkeypatch.setattr(llm_backend, "_supports_native_response_format", lambda model, response_format: True)

    def fake_infer(messages, model, tier="expensive", **kwargs):
        if "response_format" in kwargs:
            raise RuntimeError("native mode unavailable")
        return _response_with_text("still not json")

    monkeypatch.setattr(llm_backend, "infer", fake_infer)

    with pytest.raises(StructuredInferenceError, match="Structured inference failed"):
        llm_backend.infer_structured_json(
            [{"role": "user", "content": "hello"}],
            "openai/gpt-5.4",
            response_format=_SIMPLE_RESPONSE_FORMAT,
            repair_attempts=1,
        )


def test_infer_structured_json_preserves_raw_text_on_schema_validation_failure(monkeypatch):
    monkeypatch.setattr(llm_backend, "_supports_native_response_format", lambda model, response_format: False)
    monkeypatch.setattr(
        llm_backend,
        "infer",
        lambda messages, model, tier="expensive", **kwargs: _response_with_text('{"wrong":"shape"}'),
    )

    with pytest.raises(StructuredInferenceError) as exc_info:
        llm_backend.infer_structured_json(
            [{"role": "user", "content": "hello"}],
            "openai/gpt-5.4",
            response_format=_SIMPLE_RESPONSE_FORMAT,
            repair_attempts=0,
        )

    assert exc_info.value.raw_text == '{"wrong":"shape"}'
    assert "$.answer is required" in str(exc_info.value)


def test_infer_structured_json_coerces_single_array_property_schema(monkeypatch):
    retrieval_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "relevant_priors",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "prior_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["prior_ids"],
                "additionalProperties": False,
            },
        },
    }
    monkeypatch.setattr(llm_backend, "_supports_native_response_format", lambda model, response_format: False)
    monkeypatch.setattr(
        llm_backend,
        "infer",
        lambda messages, model, tier="expensive", **kwargs: _response_with_text('["p1","p2"]'),
    )

    result = llm_backend.infer_structured_json(
        [{"role": "user", "content": "hello"}],
        "openai/gpt-5.4",
        response_format=retrieval_schema,
        repair_attempts=0,
    )

    assert result["parsed"] == {"prior_ids": ["p1", "p2"]}
    assert result["raw_text"] == '["p1","p2"]'


def test_infer_structured_json_uses_qwen_two_turn_flow(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_backend, "_supports_native_response_format", lambda model, response_format: False)

    def fake_infer(messages, model, tier="expensive", **kwargs):
        calls.append({"messages": messages, "kwargs": kwargs})
        if len(calls) == 1:
            return _response_with_text("Thoughts about relevant priors")
        return _response_with_text('{"answer":"done"}')

    monkeypatch.setattr(llm_backend, "infer", fake_infer)

    result = llm_backend.infer_structured_json(
        [{"role": "system", "content": "Return an answer."}, {"role": "user", "content": "hello"}],
        "together_ai/Qwen/Qwen3.5-9B",
        response_format=_SIMPLE_RESPONSE_FORMAT,
        repair_attempts=0,
    )

    assert result["structured_mode"] == "qwen_two_turn"
    assert len(calls) == 2
    assert calls[0]["kwargs"]["max_tokens"] == llm_backend._QWEN_REASONING_MAX_TOKENS
    assert calls[1]["kwargs"]["max_tokens"] == llm_backend._QWEN_REASONING_MAX_TOKENS
    assert calls[1]["kwargs"]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert calls[1]["messages"][-2]["role"] == "assistant"
    assert calls[1]["messages"][-1]["role"] == "user"


def test_infer_structured_json_skips_native_when_capability_check_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_backend, "_supports_native_response_format", lambda model, response_format: False)

    def fake_infer(messages, model, tier="expensive", **kwargs):
        calls.append(
            {
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        return _response_with_text('{"answer":"fallback"}')

    monkeypatch.setattr(llm_backend, "infer", fake_infer)

    result = llm_backend.infer_structured_json(
        [{"role": "user", "content": "hello"}],
        "openai/gpt-5.4",
        response_format=_SIMPLE_RESPONSE_FORMAT,
        repair_attempts=0,
    )

    assert result == {
        "raw_text": '{"answer":"fallback"}',
        "parsed": {"answer": "fallback"},
        "structured_mode": "local_parse",
        "model_used": "openai/gpt-5.4",
    }
    assert len(calls) == 1
    assert "response_format" not in calls[0]["kwargs"]
    assert calls[0]["messages"][0]["role"] == "system"
    assert "Return ONLY valid JSON" in calls[0]["messages"][0]["content"]


def test_with_json_instruction_merges_into_existing_first_system_message():
    messages = [
        {"role": "system", "content": "Original system"},
        {"role": "user", "content": "hello"},
    ]

    merged = llm_backend._with_json_instruction(messages, {"type": "object"})

    assert len(merged) == 2
    assert merged[0]["role"] == "system"
    assert "Return ONLY valid JSON" in merged[0]["content"]
    assert merged[0]["content"].endswith("Original system")
    assert merged[1] == {"role": "user", "content": "hello"}


def test_payload_issue_paths_detects_non_json_friendly_values():
    issues = llm_backend._payload_issue_paths(
        {
            "messages": [
                {"role": "user", "content": "ok"},
                {"role": "user", "content": "bad\u0001text"},
            ],
            "temperature": float("nan"),
        }
    )

    assert "$.messages[1].content=contains_1_control_chars" in issues
    assert "$.temperature=non_finite_float(nan)" in issues


def _make_internal_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(internal_router)
    return TestClient(app)


def test_internal_priors_retrieve_resolves_scope_from_run(monkeypatch):
    run_id = str(uuid.uuid4())
    DB.add_run(
        run_id=run_id,
        name="Priors Internal",
        timestamp=datetime.now(timezone.utc),
        cwd="/tmp",
        command="python -m test.workflow",
        environment={},
        project_id=TEST_PROJECT_ID,
        user_id=TEST_USER_ID,
    )

    captured = {}

    async def fake_retrieve_priors_for_scope(*, user_id, project_id, context, base_path="", ignore_prior_ids=None):
        captured["scope"] = (user_id, project_id)
        captured["body"] = {
            "context": context,
            "ignore_prior_ids": ignore_prior_ids or [],
            **({"base_path": base_path} if base_path else {}),
        }
        return {"prior_count": 0, "priors": [], "rendered_priors_block": "", "priors_revision": 1}

    monkeypatch.setattr("sovara.server.routes.internal.retrieve_priors_for_scope", fake_retrieve_priors_for_scope)
    client = _make_internal_test_client()

    try:
        response = client.post(
            "/internal/priors/retrieve",
            json={
                "run_id": run_id,
                "context": "body.messages.0.content: retry",
                "ignore_prior_ids": ["p1"],
            },
        )
    finally:
        DB.backend.delete_runs_by_ids_query([run_id], user_id=None)

    assert response.status_code == 200
    assert captured["scope"] == (TEST_USER_ID, TEST_PROJECT_ID)
    assert captured["body"] == {
        "context": "body.messages.0.content: retry",
        "ignore_prior_ids": ["p1"],
    }


def test_internal_priors_query_resolves_scope_from_run(monkeypatch):
    run_id = str(uuid.uuid4())
    DB.add_run(
        run_id=run_id,
        name="Priors Query",
        timestamp=datetime.now(timezone.utc),
        cwd="/tmp",
        command="python -m test.workflow",
        environment={},
        project_id=TEST_PROJECT_ID,
        user_id=TEST_USER_ID,
    )

    captured = {}

    def fake_query_priors_for_scope(*, user_id, project_id, path=None):
        captured["scope"] = (user_id, project_id)
        captured["path"] = path
        return {"priors": [], "injected_context": "", "path": path or ""}

    monkeypatch.setattr("sovara.server.routes.internal.query_priors_for_scope", fake_query_priors_for_scope)
    client = _make_internal_test_client()

    try:
        response = client.post(
            "/internal/priors/query",
            json={
                "run_id": run_id,
                "path": "retriever/",
            },
        )
    finally:
        DB.backend.delete_runs_by_ids_query([run_id], user_id=None)

    assert response.status_code == 200
    assert captured["scope"] == (TEST_USER_ID, TEST_PROJECT_ID)
    assert captured["path"] == "retriever/"


def test_internal_priors_prefix_cache_lookup_resolves_scope_from_run(monkeypatch):
    run_id = str(uuid.uuid4())
    DB.add_run(
        run_id=run_id,
        name="Prefix Lookup",
        timestamp=datetime.now(timezone.utc),
        cwd="/tmp",
        command="python -m test.workflow",
        environment={},
        project_id=TEST_PROJECT_ID,
        user_id=TEST_USER_ID,
    )

    captured = {}

    def fake_lookup_prefix_cache_for_scope(*, user_id, project_id, clean_pairs=None, base_path=""):
        captured["scope"] = (user_id, project_id)
        captured["body"] = {"clean_pairs": clean_pairs or []}
        return {"found": True, "matched_pair_count": 1, "injected_pairs": clean_pairs or [], "prior_ids": ["p1"]}

    monkeypatch.setattr("sovara.server.routes.internal.lookup_prefix_cache_for_scope", fake_lookup_prefix_cache_for_scope)
    client = _make_internal_test_client()

    try:
        response = client.post(
            "/internal/priors/prefix-cache/lookup",
            json={
                "run_id": run_id,
                "clean_pairs": [{"key": "body.messages.0.content", "value": "Question"}],
            },
        )
    finally:
        DB.backend.delete_runs_by_ids_query([run_id], user_id=None)

    assert response.status_code == 200
    assert captured["scope"] == (TEST_USER_ID, TEST_PROJECT_ID)
    assert captured["body"] == {
        "clean_pairs": [{"key": "body.messages.0.content", "value": "Question"}],
    }


def test_internal_priors_prefix_cache_store_resolves_scope_from_run(monkeypatch):
    run_id = str(uuid.uuid4())
    DB.add_run(
        run_id=run_id,
        name="Prefix Store",
        timestamp=datetime.now(timezone.utc),
        cwd="/tmp",
        command="python -m test.workflow",
        environment={},
        project_id=TEST_PROJECT_ID,
        user_id=TEST_USER_ID,
    )

    captured = {}

    def fake_store_prefix_cache_for_scope(*, user_id, project_id, clean_pairs=None, injected_pairs=None, prior_ids=None, base_path=""):
        captured["scope"] = (user_id, project_id)
        captured["body"] = {
            "clean_pairs": clean_pairs or [],
            "injected_pairs": injected_pairs or [],
            "prior_ids": prior_ids or [],
        }
        return {"stored": True}

    monkeypatch.setattr("sovara.server.routes.internal.store_prefix_cache_for_scope", fake_store_prefix_cache_for_scope)
    client = _make_internal_test_client()

    try:
        response = client.post(
            "/internal/priors/prefix-cache/store",
            json={
                "run_id": run_id,
                "clean_pairs": [{"key": "body.messages.0.content", "value": "Question"}],
                "injected_pairs": [{"key": "body.messages.0.content", "value": "<sovara-priors>...</sovara-priors>\n\nQuestion"}],
                "prior_ids": ["p1"],
            },
        )
    finally:
        DB.backend.delete_runs_by_ids_query([run_id], user_id=None)

    assert response.status_code == 200
    assert captured["scope"] == (TEST_USER_ID, TEST_PROJECT_ID)
    assert captured["body"] == {
        "clean_pairs": [{"key": "body.messages.0.content", "value": "Question"}],
        "injected_pairs": [{"key": "body.messages.0.content", "value": "<sovara-priors>...</sovara-priors>\n\nQuestion"}],
        "prior_ids": ["p1"],
    }
