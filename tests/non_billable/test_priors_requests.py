import json
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


def test_inject_priors_formats_context_and_tracks_ids(monkeypatch):
    tracked = {}

    monkeypatch.setattr(
        priors,
        "_retrieve_priors",
        lambda path, context, model=None: [{"id": "p1", "name": "Prior 1", "content": "Use retries"}],
    )
    monkeypatch.setattr(priors, "_track_priors", lambda prior_ids: tracked.setdefault("ids", prior_ids))

    injected = priors.inject_priors(path="demo/", context="Need SQL guidance")

    assert injected == "<priors>\n## Prior 1\nUse retries\n</priors>"
    assert tracked["ids"] == ["p1"]


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
