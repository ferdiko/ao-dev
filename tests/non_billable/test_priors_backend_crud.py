import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sovara.server.priors_backend.routes import router as priors_router


def _make_priors_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(priors_router)
    return TestClient(app)


def test_priors_backend_create_list_get_update_delete_flow(monkeypatch):
    async def fake_validate_prior(**kwargs):
        class _Validation:
            approved = True
            feedback = "Looks good"
            severity = "info"
            conflicting_prior_ids = []
            path_assessment = None
            conflict_details = []

        return _Validation()

    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.validate_prior",
        fake_validate_prior,
    )

    async def fake_generate_prior_summary(**kwargs):
        return "Use retries"

    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.generate_prior_summary",
        fake_generate_prior_summary,
    )

    client = _make_priors_test_client()
    headers = {
        "x-sovara-user-id": "crud-user",
        "x-sovara-project-id": "crud-project",
    }

    create_response = client.post(
        "/api/v1/priors",
        headers=headers,
        json={
            "name": "Retry",
            "content": "Retry transient failures.",
            "path": "ops/",
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    prior_id = created["id"]
    assert created["status"] == "created"
    assert created["validation"]["severity"] == "info"
    assert created["prior_status"] == "active"

    list_response = client.get("/api/v1/priors", headers=headers)
    assert list_response.status_code == 200
    assert [prior["id"] for prior in list_response.json()["priors"]] == [prior_id]

    get_response = client.get(f"/api/v1/priors/{prior_id}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Retry"

    folder_response = client.post("/api/v1/priors/folders/ls", headers=headers, json={"path": "ops/"})
    assert folder_response.status_code == 200
    assert folder_response.json()["prior_count"] == 1
    assert folder_response.json()["priors"] == [
        {
            "id": prior_id,
            "name": "Retry",
            "summary": "Use retries",
            "path": "ops/",
            "prior_status": "active",
            "creation_trace_id": None,
            "trace_source": None,
            "created_at": created["created_at"],
            "updated_at": created["updated_at"],
            "validation_metadata": created["validation"],
        }
    ]

    update_response = client.put(
        f"/api/v1/priors/{prior_id}",
        headers=headers,
        json={"content": "Updated content."},
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "updated"
    assert update_response.json()["content"] == "Updated content."
    assert update_response.json()["summary"] == "Use retries"
    assert update_response.json()["prior_status"] == "active"

    scope_response = client.get("/api/v1/priors/scope", headers=headers)
    assert scope_response.status_code == 200
    assert scope_response.json()["revision"] == 3

    delete_response = client.delete(f"/api/v1/priors/{prior_id}", headers=headers)
    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "deleted", "id": prior_id}

    empty_list_response = client.get("/api/v1/priors", headers=headers)
    assert empty_list_response.status_code == 200
    assert empty_list_response.json()["priors"] == []


def test_priors_backend_folder_crud_flow(monkeypatch):
    async def fake_validate_prior(**kwargs):
        class _Validation:
            approved = True
            feedback = "Looks good"
            severity = "info"
            conflicting_prior_ids = []
            path_assessment = None
            conflict_details = []

        return _Validation()

    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.validate_prior",
        fake_validate_prior,
    )

    async def fake_generate_prior_summary(**kwargs):
        return "Use retries"

    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.generate_prior_summary",
        fake_generate_prior_summary,
    )

    client = _make_priors_test_client()
    headers = {
        "x-sovara-user-id": "folder-user",
        "x-sovara-project-id": "folder-project",
    }

    create_folder_response = client.post(
        "/api/v1/priors/folders",
        headers=headers,
        json={"path": "ops/retries/"},
    )
    assert create_folder_response.status_code == 200
    assert create_folder_response.json() == {"status": "created", "path": "ops/retries/"}

    create_prior_response = client.post(
        "/api/v1/priors",
        headers=headers,
        json={
            "name": "Retry",
            "content": "Retry transient failures.",
            "path": "ops/retries/",
        },
    )
    assert create_prior_response.status_code == 200
    prior_id = create_prior_response.json()["id"]

    move_folder_response = client.put(
        "/api/v1/priors/folders",
        headers=headers,
        json={"path": "ops/retries/", "new_path": "ops/resilience/"},
    )
    assert move_folder_response.status_code == 200
    assert move_folder_response.json() == {
        "status": "updated",
        "path": "ops/retries/",
        "new_path": "ops/resilience/",
    }

    prior_response = client.get(f"/api/v1/priors/{prior_id}", headers=headers)
    assert prior_response.status_code == 200
    assert prior_response.json()["path"] == "ops/resilience/"

    delete_folder_response = client.post(
        "/api/v1/priors/folders/delete",
        headers=headers,
        json={"path": "ops/resilience/"},
    )
    assert delete_folder_response.status_code == 200
    assert delete_folder_response.json() == {"status": "deleted", "path": "ops/resilience/"}

    empty_list_response = client.get("/api/v1/priors", headers=headers)
    assert empty_list_response.status_code == 200
    assert empty_list_response.json()["priors"] == []


def test_priors_backend_create_folder_conflicts_when_name_exists():
    client = _make_priors_test_client()
    headers = {
        "x-sovara-user-id": "folder-conflict-user",
        "x-sovara-project-id": "folder-conflict-project",
    }

    first_response = client.post(
        "/api/v1/priors/folders",
        headers=headers,
        json={"path": "ops/retries/"},
    )
    assert first_response.status_code == 200

    conflict_response = client.post(
        "/api/v1/priors/folders",
        headers=headers,
        json={"path": "ops/retries/"},
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json()["detail"] == "Folder 'ops/retries/' already exists"


def test_priors_backend_update_regenerates_summary_when_content_changes(monkeypatch):
    async def fake_validate_prior(**kwargs):
        class _Validation:
            approved = True
            feedback = "Looks good"
            severity = "info"
            conflicting_prior_ids = []
            path_assessment = None
            conflict_details = []

        return _Validation()

    generated = iter(["Original summary", "Updated summary"])

    async def fake_generate_prior_summary(**kwargs):
        return next(generated)

    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.validate_prior",
        fake_validate_prior,
    )
    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.generate_prior_summary",
        fake_generate_prior_summary,
    )

    client = _make_priors_test_client()
    headers = {
        "x-sovara-user-id": "summary-user",
        "x-sovara-project-id": "summary-project",
    }

    create_response = client.post(
        "/api/v1/priors",
        headers=headers,
        json={
            "name": "Retry",
            "content": "Retry transient failures.",
            "path": "ops/",
        },
    )
    assert create_response.status_code == 200
    prior_id = create_response.json()["id"]
    assert create_response.json()["summary"] == "Original summary"

    update_response = client.put(
        f"/api/v1/priors/{prior_id}",
        headers=headers,
        json={"content": "Use exponential backoff for retries."},
    )
    assert update_response.status_code == 200
    assert update_response.json()["summary"] == "Updated summary"

    get_response = client.get(f"/api/v1/priors/{prior_id}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["summary"] == "Updated summary"


def test_priors_backend_draft_create_submit_and_copy_flow(monkeypatch):
    async def fake_validate_prior(**kwargs):
        class _Validation:
            approved = True
            feedback = "Looks good"
            severity = "info"
            conflicting_prior_ids = []
            path_assessment = None
            conflict_details = []

        return _Validation()

    async def fake_generate_prior_summary(**kwargs):
        return "Generated summary"

    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.validate_prior",
        fake_validate_prior,
    )
    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.generate_prior_summary",
        fake_generate_prior_summary,
    )

    client = _make_priors_test_client()
    headers = {
        "x-sovara-user-id": f"draft-user-{uuid.uuid4()}",
        "x-sovara-project-id": f"draft-project-{uuid.uuid4()}",
    }

    draft_response = client.post(
        "/api/v1/priors/drafts",
        headers=headers,
        json={
            "name": "Untitled",
            "content": "# Untitled\n\nDraft content.",
            "path": "ops/",
        },
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()
    assert draft["status"] == "created"
    assert draft["summary"] == ""
    assert draft["prior_status"] == "draft"

    fetched_draft = client.get(f"/api/v1/priors/{draft['id']}", headers=headers)
    assert fetched_draft.status_code == 200
    assert fetched_draft.json()["prior_status"] == "draft"

    draft_scope = client.get("/api/v1/priors/scope", headers=headers)
    assert draft_scope.status_code == 200
    assert draft_scope.json()["revision"] == 1

    submit_response = client.post(
        f"/api/v1/priors/{draft['id']}/submit",
        headers=headers,
        json={"content": "# Accepted\n\nShip it."},
    )
    assert submit_response.status_code == 200
    submitted = submit_response.json()
    assert submitted["status"] == "submitted"
    assert submitted["summary"] == "Generated summary"
    assert submitted["path"] == "ops/"
    assert submitted["validation"]["severity"] == "info"
    assert submitted["prior_status"] == "active"

    submitted_scope = client.get("/api/v1/priors/scope", headers=headers)
    assert submitted_scope.status_code == 200
    assert submitted_scope.json()["revision"] == 2

    refetched = client.get(f"/api/v1/priors/{draft['id']}", headers=headers)
    assert refetched.status_code == 200
    assert refetched.json()["prior_status"] == "active"

    copy_response = client.post(
        "/api/v1/priors/items/copy",
        headers=headers,
        json={
            "items": [{"kind": "prior", "id": draft["id"]}],
            "destination_path": "ops/archive/",
            "as_draft": True,
        },
    )
    assert copy_response.status_code == 200
    copied_prior_id = copy_response.json()["items"][0]["id"]

    copied_prior = client.get(f"/api/v1/priors/{copied_prior_id}", headers=headers)
    assert copied_prior.status_code == 200
    assert copied_prior.json()["prior_status"] == "draft"
    assert copied_prior.json()["validation_metadata"] is None

    copied_scope = client.get("/api/v1/priors/scope", headers=headers)
    assert copied_scope.status_code == 200
    assert copied_scope.json()["revision"] == 2


def test_priors_backend_metadata_only_update_skips_validation_and_summary_generation(monkeypatch):
    async def fake_validate_prior(**kwargs):
        class _Validation:
            approved = True
            feedback = "Looks good"
            severity = "info"
            conflicting_prior_ids = []
            path_assessment = None
            conflict_details = []

        return _Validation()

    async def fake_generate_prior_summary(**kwargs):
        return "Original summary"

    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.validate_prior",
        fake_validate_prior,
    )
    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.generate_prior_summary",
        fake_generate_prior_summary,
    )

    client = _make_priors_test_client()
    headers = {
        "x-sovara-user-id": "metadata-update-user",
        "x-sovara-project-id": "metadata-update-project",
    }

    client.post(
        "/api/v1/priors/folders",
        headers=headers,
        json={"path": "ops/renamed/"},
    )

    create_response = client.post(
        "/api/v1/priors",
        headers=headers,
        json={
            "name": "Retry",
            "content": "Retry transient failures.",
            "path": "ops/",
        },
    )
    assert create_response.status_code == 200
    prior_id = create_response.json()["id"]
    assert create_response.json()["summary"] == "Original summary"

    async def fail_validate_prior(**kwargs):
        raise AssertionError("metadata-only updates should not trigger validation")

    async def fail_generate_prior_summary(**kwargs):
        raise AssertionError("metadata-only updates should not regenerate summary")

    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.validate_prior",
        fail_validate_prior,
    )
    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.generate_prior_summary",
        fail_generate_prior_summary,
    )

    rename_response = client.put(
        f"/api/v1/priors/{prior_id}",
        headers=headers,
        json={"name": "Retry Renamed"},
    )
    assert rename_response.status_code == 200
    assert rename_response.json()["status"] == "updated"
    assert rename_response.json()["name"] == "Retry Renamed"
    assert rename_response.json()["summary"] == "Original summary"
    assert rename_response.json()["validation"] is None

    move_response = client.put(
        f"/api/v1/priors/{prior_id}",
        headers=headers,
        json={"path": "ops/renamed/"},
    )
    assert move_response.status_code == 200
    assert move_response.json()["status"] == "updated"
    assert move_response.json()["path"] == "ops/renamed/"
    assert move_response.json()["summary"] == "Original summary"
    assert move_response.json()["validation"] is None


def test_priors_backend_item_copy_move_delete_flow(monkeypatch):
    async def fake_validate_prior(**kwargs):
        class _Validation:
            approved = True
            feedback = "Looks good"
            severity = "info"
            conflicting_prior_ids = []
            path_assessment = None
            conflict_details = []

        return _Validation()

    async def fake_generate_prior_summary(**kwargs):
        return "Reusable prior"

    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.validate_prior",
        fake_validate_prior,
    )
    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.generate_prior_summary",
        fake_generate_prior_summary,
    )

    client = _make_priors_test_client()
    headers = {
        "x-sovara-user-id": f"items-user-{uuid.uuid4()}",
        "x-sovara-project-id": f"items-project-{uuid.uuid4()}",
    }

    client.post("/api/v1/priors/folders", headers=headers, json={"path": "sql_generator/library/"})
    client.post("/api/v1/priors/folders", headers=headers, json={"path": "sql_generator/archive/"})
    client.post("/api/v1/priors/folders", headers=headers, json={"path": "sql_generator/staging/"})
    create_prior_response = client.post(
        "/api/v1/priors",
        headers=headers,
        json={
            "name": "Retry",
            "content": "Retry transient failures.",
            "path": "sql_generator/library/",
        },
    )
    assert create_prior_response.status_code == 200
    prior_id = create_prior_response.json()["id"]

    copy_response = client.post(
        "/api/v1/priors/items/copy",
        headers=headers,
        json={
            "items": [
                {"kind": "prior", "id": prior_id},
                {"kind": "folder", "path": "sql_generator/library/"},
            ],
            "destination_path": "sql_generator/archive/",
        },
    )
    assert copy_response.status_code == 200
    copied = copy_response.json()
    assert copied["status"] == "copied"
    assert copied["count"] == 2
    copied_prior = next(item for item in copied["items"] if item["kind"] == "prior")
    copied_folder = next(item for item in copied["items"] if item["kind"] == "folder")
    assert copied_prior["path"] == "sql_generator/archive/"
    assert copied_folder["path"] == "sql_generator/archive/library/"

    move_response = client.post(
        "/api/v1/priors/items/move",
        headers=headers,
        json={
            "items": [{"kind": "folder", "path": "sql_generator/archive/library/"}],
            "destination_path": "sql_generator/staging/",
        },
    )
    assert move_response.status_code == 200
    assert move_response.json() == {
        "status": "moved",
        "items": [{"kind": "folder", "path": "sql_generator/staging/library/", "name": "library"}],
        "count": 1,
    }

    delete_response = client.post(
        "/api/v1/priors/items/delete",
        headers=headers,
        json={
            "items": [
                {"kind": "prior", "id": copied_prior["id"]},
                {"kind": "folder", "path": "sql_generator/staging/library/"},
            ],
        },
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "deleted", "count": 2}

    list_response = client.get("/api/v1/priors", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["priors"] == [
        {
            "id": prior_id,
            "name": "Retry",
            "summary": "Reusable prior",
            "content": "Retry transient failures.",
            "path": "sql_generator/library/",
            "prior_status": "active",
            "creation_trace_id": None,
            "trace_source": None,
            "created_at": create_prior_response.json()["created_at"],
            "updated_at": create_prior_response.json()["updated_at"],
            "validation_metadata": create_prior_response.json()["validation"],
        }
    ]

    scope_response = client.get("/api/v1/priors/scope", headers=headers)
    assert scope_response.status_code == 200
    assert scope_response.json()["revision"] == 5


def test_priors_backend_item_delete_logs_prior_and_folder_counts(monkeypatch):
    async def fake_validate_prior(**kwargs):
        class _Validation:
            approved = True
            feedback = "Looks good"
            severity = "info"
            conflicting_prior_ids = []
            path_assessment = None
            conflict_details = []

        return _Validation()

    async def fake_generate_prior_summary(**kwargs):
        return "Reusable prior"

    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.validate_prior",
        fake_validate_prior,
    )
    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.generate_prior_summary",
        fake_generate_prior_summary,
    )

    log_messages: list[tuple[str, tuple[object, ...]]] = []
    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.logger.info",
        lambda message, *args: log_messages.append((message, args)),
    )

    client = _make_priors_test_client()
    headers = {
        "x-sovara-user-id": f"delete-log-user-{uuid.uuid4()}",
        "x-sovara-project-id": f"delete-log-project-{uuid.uuid4()}",
    }

    client.post("/api/v1/priors/folders", headers=headers, json={"path": "ops/retries/"})
    client.post("/api/v1/priors/folders", headers=headers, json={"path": "ops/retries/nested/"})
    create_prior_response = client.post(
        "/api/v1/priors",
        headers=headers,
        json={
            "name": "Retry",
            "content": "Retry transient failures.",
            "path": "ops/",
        },
    )
    prior_id = create_prior_response.json()["id"]

    delete_response = client.post(
        "/api/v1/priors/items/delete",
        headers=headers,
        json={
            "items": [
                {"kind": "prior", "id": prior_id},
                {"kind": "folder", "path": "ops/retries/"},
            ],
        },
    )

    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "deleted", "count": 2}
    assert (
        "Deleted %s prior items (%s priors, %s folders)",
        (2, 1, 1),
    ) in log_messages


def test_priors_backend_keeps_empty_folders_after_prior_delete_and_move(monkeypatch):
    async def fake_validate_prior(**kwargs):
        class _Validation:
            approved = True
            feedback = "Looks good"
            severity = "info"
            conflicting_prior_ids = []
            path_assessment = None
            conflict_details = []

        return _Validation()

    async def fake_generate_prior_summary(**kwargs):
        return "Reusable prior"

    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.validate_prior",
        fake_validate_prior,
    )
    monkeypatch.setattr(
        "sovara.server.priors_backend.routes.generate_prior_summary",
        fake_generate_prior_summary,
    )

    client = _make_priors_test_client()
    headers = {
        "x-sovara-user-id": f"empty-folders-user-{uuid.uuid4()}",
        "x-sovara-project-id": f"empty-folders-project-{uuid.uuid4()}",
    }

    client.post("/api/v1/priors/folders", headers=headers, json={"path": "ops/source/"})
    client.post("/api/v1/priors/folders", headers=headers, json={"path": "ops/dest/"})

    create_response = client.post(
        "/api/v1/priors",
        headers=headers,
        json={
            "name": "Retry",
            "content": "Retry transient failures.",
            "path": "ops/source/",
        },
    )
    prior_id = create_response.json()["id"]

    move_response = client.post(
        "/api/v1/priors/items/move",
        headers=headers,
        json={
            "items": [{"kind": "prior", "id": prior_id}],
            "destination_path": "ops/dest/",
        },
    )
    assert move_response.status_code == 200

    source_folder_response = client.post(
        "/api/v1/priors/folders/ls",
        headers=headers,
        json={"path": "ops/source/"},
    )
    assert source_folder_response.status_code == 200
    assert source_folder_response.json()["prior_count"] == 0
    assert source_folder_response.json()["priors"] == []
    assert source_folder_response.json()["folders"] == []

    delete_response = client.post(
        "/api/v1/priors/items/delete",
        headers=headers,
        json={
            "items": [{"kind": "prior", "id": prior_id}],
        },
    )
    assert delete_response.status_code == 200

    dest_folder_response = client.post(
        "/api/v1/priors/folders/ls",
        headers=headers,
        json={"path": "ops/dest/"},
    )
    assert dest_folder_response.status_code == 200
    assert dest_folder_response.json()["prior_count"] == 0
    assert dest_folder_response.json()["priors"] == []
    assert dest_folder_response.json()["folders"] == []
