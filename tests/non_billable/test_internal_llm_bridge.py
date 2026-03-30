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


def _make_internal_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(internal_router)
    return TestClient(app)


def test_internal_llm_infer_forwards_timeout_and_extra_kwargs(monkeypatch):
    captured = {}

    def fake_infer_structured_json(messages, model, tier="expensive", response_format=None, repair_attempts=1, **kwargs):
        captured["messages"] = messages
        captured["model"] = model
        captured["tier"] = tier
        captured["response_format"] = response_format
        captured["repair_attempts"] = repair_attempts
        captured["kwargs"] = kwargs
        return {
            "raw_text": '{"answer":"ok"}',
            "parsed": {"answer": "ok"},
            "structured_mode": "local_parse",
            "model_used": model,
        }

    monkeypatch.setattr("sovara.server.routes.internal.infer_structured_json", fake_infer_structured_json)
    client = _make_internal_test_client()

    response = client.post(
        "/internal/llm/infer",
        json={
            "purpose": "priors_retrieval",
            "model": "openai/gpt-5.4",
            "tier": "cheap",
            "messages": [{"role": "user", "content": "hi"}],
            "response_format": _SIMPLE_RESPONSE_FORMAT,
            "timeout_ms": 1500,
            "repair_attempts": 2,
            "extra_body": {"thinking_token_budget": 200},
        },
    )

    assert response.status_code == 200
    assert response.json()["structured_mode"] == "local_parse"
    assert captured["tier"] == "cheap"
    assert captured["repair_attempts"] == 2
    assert captured["kwargs"]["timeout"] == 1.5
    assert captured["kwargs"]["extra_body"] == {"thinking_token_budget": 200}


def test_internal_llm_infer_maps_structured_error_to_422(monkeypatch):
    def fake_infer_structured_json(*args, **kwargs):
        raise StructuredInferenceError(
            "schema mismatch",
            raw_text="oops",
            structured_mode="failed",
        )

    monkeypatch.setattr("sovara.server.routes.internal.infer_structured_json", fake_infer_structured_json)
    client = _make_internal_test_client()

    response = client.post(
        "/internal/llm/infer",
        json={
            "purpose": "priors_validation",
            "model": "openai/gpt-5.4",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "error": "schema mismatch",
        "raw_text": "oops",
        "structured_mode": "failed",
    }


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

    def fake_retrieve_priors(self, body):
        captured["scope"] = (self.user_id, self.project_id)
        captured["body"] = body
        return {"prior_count": 0, "priors": [], "rendered_priors_block": "", "priors_revision": 1}

    monkeypatch.setattr("sovara.server.priors_client.PriorsBackendClient.retrieve_priors", fake_retrieve_priors)
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
        "model": None,
        "ignore_prior_ids": ["p1"],
    }


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

    def fake_lookup_prefix_cache(self, body):
        captured["scope"] = (self.user_id, self.project_id)
        captured["body"] = body
        return {"found": True, "matched_pair_count": 1, "injected_pairs": body["clean_pairs"], "prior_ids": ["p1"]}

    monkeypatch.setattr("sovara.server.priors_client.PriorsBackendClient.lookup_prefix_cache", fake_lookup_prefix_cache)
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

    def fake_store_prefix_cache(self, body):
        captured["scope"] = (self.user_id, self.project_id)
        captured["body"] = body
        return {"stored": True}

    monkeypatch.setattr("sovara.server.priors_client.PriorsBackendClient.store_prefix_cache", fake_store_prefix_cache)
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
