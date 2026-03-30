from fastapi.testclient import TestClient

from sovara.server.priors_backend.app import create_app
from sovara.server.priors_backend.storage import PriorStore


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
    client = TestClient(create_app())

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


def test_priors_retrieve_endpoint_returns_selected_priors_and_scope_revision(monkeypatch):
    store = PriorStore("retrieve-user", "retrieve-project")
    store.create("p1", "Retry", "Retries", "Retry transient failures.", path="ops/")
    store.create("p2", "Cache", "Caching", "Cache stable responses.", path="ops/")
    calls = {"count": 0}

    async def fake_infer_structured_json(*, purpose, messages, model, tier, response_format, timeout_ms, repair_attempts, **extra):
        calls["count"] += 1
        priors_message = messages[-1]["content"]
        if "ID: p1" in priors_message and "ID: p2" not in priors_message:
            return {
                "raw_text": '{"prior_ids":["p1"]}',
                "parsed": {"prior_ids": ["p1"]},
                "structured_mode": "local_parse",
                "model_used": model,
            }
        return {
            "raw_text": '{"prior_ids":[]}',
            "parsed": {"prior_ids": []},
            "structured_mode": "local_parse",
            "model_used": model,
        }

    monkeypatch.setattr(
        "sovara.server.priors_backend.llm.lesson_retriever.infer_structured_json",
        fake_infer_structured_json,
    )

    client = TestClient(create_app())
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
    assert data["model_used"] == "openai/gpt-5.4-mini"
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
