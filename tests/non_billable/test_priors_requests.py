import json
import io
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from sovara.cli import so_tool
from sovara.common.config import Config
from sovara.runner import priors


class _DummyResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_config_ignores_unknown_fields(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "python_executable: /usr/bin/python3\nunknown_field: value\n",
        encoding="utf-8",
    )
    loaded = Config.from_yaml_file(str(config_path))

    assert loaded.python_executable == "/usr/bin/python3"
    assert not hasattr(loaded, "unknown_field")


def test_cli_priors_request_does_not_send_api_key_header(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["timeout"] = timeout
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _DummyResponse({"status": "ok"})

    monkeypatch.setenv("SOVARA_API_KEY", "secret")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = so_tool._priors_request("POST", "/api/v1/priors", {"name": "test"})

    assert result == {"status": "ok"}
    assert captured["timeout"] == 120
    assert captured["headers"]["content-type"] == "application/json"
    assert "x-api-key" not in captured["headers"]


def test_runner_priors_request_does_not_send_api_key_header(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["timeout"] = timeout
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _DummyResponse({"priors": []})

    monkeypatch.setenv("SOVARA_API_KEY", "secret")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = priors._priors_request("/query/priors", {"path": "demo/"})

    assert result == {"priors": []}
    assert captured["timeout"] == 300
    assert captured["headers"]["content-type"] == "application/json"
    assert "x-api-key" not in captured["headers"]


def test_runner_priors_request_uses_current_run_scope_headers(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _DummyResponse({"priors": []})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(priors, "get_run_id", lambda: "run-123")
    monkeypatch.setattr(
        priors.DB,
        "query_one",
        lambda query, params: {"user_id": "user-123", "project_id": "project-123"},
    )

    result = priors._priors_request("/query/priors", {"path": "demo/"})

    assert result == {"priors": []}
    assert captured["headers"]["x-sovara-user-id"] == "user-123"
    assert captured["headers"]["x-sovara-project-id"] == "project-123"


def test_inject_priors_formats_context_and_tracks_ids(monkeypatch):
    tracked = {}

    monkeypatch.setattr(
        priors,
        "_retrieve_priors",
        lambda path, context, model=None: [{"id": "p1", "name": "Prior 1", "content": "Use retries"}],
    )
    monkeypatch.setattr(priors, "_track_priors", lambda prior_ids: tracked.setdefault("ids", prior_ids))

    injected = priors.inject_priors(path="demo/", context="Need SQL guidance")

    assert injected == (
        "<sovara-priors>\n"
        '<!-- {"manual":true,"priors":[{"id":"p1"}]} -->\n'
        "## Prior 1\nUse retries\n"
        "</sovara-priors>"
    )
    assert tracked["ids"] == ["p1"]


def test_inject_priors_formats_manual_block_for_method_all(monkeypatch):
    tracked = {}

    monkeypatch.setattr(
        priors,
        "_query_priors",
        lambda path=None: (
            [{"id": "p1", "name": "Prior 1", "content": "Use retries"}],
            "<sovara-priors>\n<!-- {\"priors\":[{\"id\":\"p1\"}]} -->\n## Prior 1\nUse retries\n</sovara-priors>",
        ),
    )
    monkeypatch.setattr(priors, "_track_priors", lambda prior_ids: tracked.setdefault("ids", prior_ids))

    injected = priors.inject_priors(path="demo/", method="all")

    assert injected == (
        "<sovara-priors>\n"
        '<!-- {"manual":true,"priors":[{"id":"p1"}]} -->\n'
        "## Prior 1\nUse retries\n"
        "</sovara-priors>"
    )
    assert tracked["ids"] == ["p1"]


def test_retrieve_priors_uses_current_backend_route(monkeypatch):
    captured = {}

    def fake_priors_request(endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        return {"priors": []}

    monkeypatch.setattr(priors, "_priors_request", fake_priors_request)

    result = priors._retrieve_priors(path="demo/", context="Need SQL guidance", model="openai/gpt-5.4-mini")

    assert result == []
    assert captured["endpoint"] == "/priors/retrieve"
    assert captured["payload"] == {
        "context": "Need SQL guidance",
        "base_path": "demo/",
        "model": "openai/gpt-5.4-mini",
    }


def test_query_priors_uses_internal_route_when_run_is_active(monkeypatch):
    captured = {}

    monkeypatch.setattr(priors, "get_run_id", lambda: "run-123")

    def fake_http_post(endpoint, data, timeout=None):
        captured["endpoint"] = endpoint
        captured["data"] = data
        captured["timeout"] = timeout
        return {"priors": [], "injected_context": ""}

    monkeypatch.setattr(priors, "http_post", fake_http_post)

    result = priors._query_priors(path="demo/")

    assert result == ([], "")
    assert captured["endpoint"] == "/internal/priors/query"
    assert captured["data"] == {"run_id": "run-123", "path": "demo/"}
    assert captured["timeout"] == 35.0


def test_retrieve_priors_uses_internal_route_when_run_is_active(monkeypatch):
    captured = {}

    monkeypatch.setattr(priors, "get_run_id", lambda: "run-123")

    def fake_http_post(endpoint, data, timeout=None):
        captured["endpoint"] = endpoint
        captured["data"] = data
        captured["timeout"] = timeout
        return {"priors": []}

    monkeypatch.setattr(priors, "http_post", fake_http_post)

    result = priors._retrieve_priors(path="demo/", context="Need SQL guidance", model="openai/gpt-5.4-mini")

    assert result == []
    assert captured["endpoint"] == "/internal/priors/retrieve"
    assert captured["data"] == {
        "run_id": "run-123",
        "context": "Need SQL guidance",
        "base_path": "demo/",
        "model": "openai/gpt-5.4-mini",
        "ignore_prior_ids": [],
    }
    assert captured["timeout"] == 35.0


def test_inject_priors_raises_actionable_error_for_missing_folder(monkeypatch):
    def fail_retrieve(path, context, model=None):
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:5960/api/v1/priors/retrieve",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b'{"detail":"Folder not found"}'),
        )

    monkeypatch.setattr(priors, "_retrieve_priors", fail_retrieve)

    with pytest.raises(ValueError, match="prior folder 'demo/' does not exist"):
        priors.inject_priors(path="demo/", context="Need SQL guidance")


def test_cli_priors_retrieve_command_uses_current_backend_route(monkeypatch):
    captured = {}

    def fake_priors_request(method, endpoint, data):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["data"] = data
        return {"status": "ok"}

    def fake_output_json(data):
        captured["output"] = data

    monkeypatch.setattr(so_tool, "_priors_request", fake_priors_request)
    monkeypatch.setattr(so_tool, "output_json", fake_output_json)

    so_tool.priors_retrieve_command(
        SimpleNamespace(
            context="Need SQL guidance",
            path="demo/",
            model="openai/gpt-5.4-mini",
        )
    )

    assert captured["method"] == "POST"
    assert captured["endpoint"] == "/api/v1/priors/retrieve"
    assert captured["data"] == {
        "context": "Need SQL guidance",
        "base_path": "demo/",
        "model": "openai/gpt-5.4-mini",
    }
    assert captured["output"] == {"status": "ok"}


def test_build_restructure_execute_body_from_proposal_file(tmp_path):
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps({
            "task_id": "task-123",
            "moves": [{"prior_id": "p1", "current_path": "a/", "new_path": "b/"}],
            "new_folders": ["b/"],
            "snapshot": "snap-1",
        }),
        encoding="utf-8",
    )

    args = SimpleNamespace(
        task_id=None,
        proposal_file=str(proposal_path),
        moves_file=None,
        base_path=None,
        snapshot=None,
        new_folder=None,
    )

    body = so_tool._build_restructure_execute_body(args)

    assert body == {
        "task_id": "task-123",
        "moves": [{"prior_id": "p1", "current_path": "a/", "new_path": "b/"}],
        "new_folders": ["b/"],
        "snapshot": "snap-1",
    }


def test_build_restructure_execute_body_applies_cli_overrides(tmp_path):
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps({"task_id": "task-123"}), encoding="utf-8")

    moves_path = tmp_path / "moves.json"
    moves_path.write_text(
        json.dumps([{"prior_id": "p2", "current_path": "x/", "new_path": "y/"}]),
        encoding="utf-8",
    )

    args = SimpleNamespace(
        task_id="task-override",
        proposal_file=str(proposal_path),
        moves_file=str(moves_path),
        base_path="root/",
        snapshot="snap-2",
        new_folder=["y/"],
    )

    body = so_tool._build_restructure_execute_body(args)

    assert body == {
        "task_id": "task-override",
        "moves": [{"prior_id": "p2", "current_path": "x/", "new_path": "y/"}],
        "base_path": "root/",
        "snapshot": "snap-2",
        "new_folders": ["y/"],
    }


def test_build_restructure_execute_body_requires_input():
    args = SimpleNamespace(
        task_id=None,
        proposal_file=None,
        moves_file=None,
        base_path=None,
        snapshot=None,
        new_folder=None,
    )

    with pytest.raises(ValueError, match="Provide --task-id, --proposal-file, or a standalone execute body"):
        so_tool._build_restructure_execute_body(args)
