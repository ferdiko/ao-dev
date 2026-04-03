import json
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sovara.server.llm_backend import resolve_model
from sovara.server.priors_backend.llm import lesson_retriever
from sovara.server.priors_backend.constants import PRIORS_BACKEND_HOME, SCOPE_METADATA_FILENAME
from sovara.server.priors_backend.routes import router as priors_router
from sovara.server.priors_backend.storage import PriorStore
from sovara.server.database_manager import DB


def _make_priors_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(priors_router)
    return TestClient(app)


def test_prior_store_scopes_files_and_metadata_by_user_and_project():
    store = PriorStore("user-a", "project-a")
    created = store.create(
        prior_id="p1",
        name="Retry Advice",
        summary="Use retries",
        content="Retry transient failures.",
        path="retriever/",
        validation_metadata={"severity": "info"},
    )

    same_scope = PriorStore("user-a", "project-a")
    other_scope = PriorStore("user-b", "project-b")

    assert created["path"] == "retriever/"
    assert same_scope.get("p1")["name"] == "Retry Advice"
    assert same_scope.read_scope_metadata()["user_id"] == "user-a"
    assert same_scope.read_scope_metadata()["project_id"] == "project-a"
    assert other_scope.get("p1") is None


def test_priors_scope_endpoint_uses_header_scope():
    client = _make_priors_test_client()

    response = client.get(
        "/api/v1/priors/scope",
        headers={
            "x-sovara-user-id": "scope-user",
            "x-sovara-project-id": "scope-project",
        },
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == "scope-user"
    assert response.json()["project_id"] == "scope-project"
    assert response.json()["revision"] == 1


def test_prior_store_migrates_legacy_scope_metadata_into_db():
    user_id = "legacy-scope-user"
    project_id = "legacy-scope-project"
    base = os.path.join(PRIORS_BACKEND_HOME, user_id, project_id)
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, SCOPE_METADATA_FILENAME), "w", encoding="utf-8") as handle:
        json.dump(
            {
                "user_id": user_id,
                "project_id": project_id,
                "revision": 7,
                "updated_at": "2026-04-03T12:00:00+00:00",
            },
            handle,
        )

    store = PriorStore(user_id, project_id)
    scope = store.read_scope_metadata()

    assert scope["revision"] == 7
    assert scope["updated_at"] == "2026-04-03T12:00:00+00:00"
    assert DB.get_priors_scope(user_id=user_id, project_id=project_id)["revision"] == 7


def test_priors_retrieve_endpoint_returns_selected_priors_and_scope_revision(monkeypatch):
    store = PriorStore("retrieve-user", "retrieve-project")
    store.create("p1", "Retry", "Retries", "Retry transient failures.", path="ops/")
    store.create("p2", "Cache", "Caching", "Cache stable responses.", path="ops/")
    calls = {"count": 0}

    async def fake_infer_structured_json(*, messages, tier, response_format, timeout_ms, repair_attempts, **extra):
        calls["count"] += 1
        priors_message = messages[-1]["content"]
        if "ID: p1" in priors_message and "ID: p2" not in priors_message:
            return {
                "raw_text": '{"prior_ids":["p1"]}',
                "parsed": {"prior_ids": ["p1"]},
                "structured_mode": "local_parse",
                "model_used": resolve_model(None, tier),
            }
        return {
            "raw_text": '{"prior_ids":[]}',
            "parsed": {"prior_ids": []},
            "structured_mode": "local_parse",
            "model_used": resolve_model(None, tier),
        }

    monkeypatch.setattr(
        "sovara.server.priors_backend.llm.lesson_retriever.infer_structured_json",
        fake_infer_structured_json,
    )

    client = _make_priors_test_client()
    payload = {
        "context": "Need guidance for transient API failures",
        "base_path": "ops/",
        "ignore_prior_ids": ["p2"],
    }
    response = client.post(
        "/api/v1/priors/retrieve",
        headers={
            "x-sovara-user-id": "retrieve-user",
            "x-sovara-project-id": "retrieve-project",
        },
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["priors_revision"] == 1
    assert data["prior_count"] == 1
    assert [prior["id"] for prior in data["priors"]] == ["p1"]
    assert data["priors"][0]["path"] == "ops/"
    assert data["model_used"] == resolve_model(None, "cheap")
    assert data["rendered_priors_block"].startswith('<sovara-priors>\n<!-- {"priors":[{"id":"p1"}]} -->')
    assert calls["count"] == 1

    cached_response = client.post(
        "/api/v1/priors/retrieve",
        headers={
            "x-sovara-user-id": "retrieve-user",
            "x-sovara-project-id": "retrieve-project",
        },
        json=payload,
    )

    assert cached_response.status_code == 200
    assert cached_response.json() == data
    assert calls["count"] == 1

    store.bump_scope_revision()
    refreshed_response = client.post(
        "/api/v1/priors/retrieve",
        headers={
            "x-sovara-user-id": "retrieve-user",
            "x-sovara-project-id": "retrieve-project",
        },
        json=payload,
    )

    assert refreshed_response.status_code == 200
    assert refreshed_response.json()["priors_revision"] == 2
    assert calls["count"] == 2


def test_fit_context_to_token_budget_trims_only_middle(monkeypatch):
    context = "A" * 2000 + "B" * 2000
    priors_context = "ID: p1\nSummary: something"

    estimates = iter([10000, 4800])
    monkeypatch.setattr(lesson_retriever, "_estimate_prompt_tokens", lambda model, messages: next(estimates))

    trimmed, original_estimate, trimmed_estimate = lesson_retriever._fit_context_to_token_budget(
        context,
        priors_context,
        resolve_model(None, "cheap"),
    )

    assert original_estimate == 10000
    assert trimmed_estimate == 4800
    assert trimmed.startswith("A" * 100)
    assert trimmed.endswith("B" * 100)
    assert lesson_retriever._RETRIEVAL_TRIM_MARKER in trimmed


def test_query_priors_returns_404_for_missing_folder():
    client = _make_priors_test_client()

    response = client.post(
        "/api/v1/query/priors",
        headers={
            "x-sovara-user-id": "missing-query-user",
            "x-sovara-project-id": "missing-query-project",
        },
        json={"path": "beaver/retriever/"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found"


def test_priors_retrieve_endpoint_returns_404_for_missing_base_path():
    client = _make_priors_test_client()

    response = client.post(
        "/api/v1/priors/retrieve",
        headers={
            "x-sovara-user-id": "missing-retrieve-user",
            "x-sovara-project-id": "missing-retrieve-project",
        },
        json={
            "context": "Need guidance for transient API failures",
            "base_path": "beaver/retriever/",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found"


def test_prefix_cache_is_scoped_by_model():
    user_id = "prefix-model-user"
    project_id = "prefix-model-project"
    base_path = ""
    clean_pairs = [{"key": "body.messages.0.content", "value": "Question"}]
    injected_pairs = [{"key": "body.messages.0.content", "value": "<sovara-priors>...</sovara-priors>\n\nQuestion"}]

    DB.store_prefix_cache(
        user_id=user_id,
        project_id=project_id,
        base_path=base_path,
        model="model-a",
        clean_pairs=clean_pairs,
        injected_pairs=injected_pairs,
        prior_ids=["p1"],
    )

    assert DB.lookup_prefix_cache(
        user_id=user_id,
        project_id=project_id,
        base_path=base_path,
        model="model-a",
        clean_pairs=clean_pairs,
    ) == {
        "matched_pair_count": 1,
        "injected_pairs": injected_pairs,
        "prior_ids": ["p1"],
    }

    assert DB.lookup_prefix_cache(
        user_id=user_id,
        project_id=project_id,
        base_path=base_path,
        model="model-b",
        clean_pairs=clean_pairs,
    ) is None

    DB.clear_scope_prefix_cache(user_id=user_id, project_id=project_id)
