import asyncio
import json
import sys
import types
from types import SimpleNamespace

from fastapi import HTTPException

from sovara.server.graph_analysis.inference_server import _ensure_prefetch_future, _graph_fingerprint
from sovara.server.graph_analysis.trace_chat.main import handle_question
from sovara.server.graph_analysis.trace_chat.utils.trace import Trace
from sovara.server.routes.ui import ChatMessageRequest, chat


def test_graph_fingerprint_accepts_uuid_shaped_nodes():
    graph_data = {"nodes": [{"uuid": "node-a", "input": "in", "output": "out"}]}
    legacy_graph_data = {"nodes": [{"id": "node-a", "input": "in", "output": "out"}]}

    assert _graph_fingerprint(graph_data) == _graph_fingerprint(legacy_graph_data)


def test_graph_fingerprint_ignores_deprecated_model_or_tool_key():
    graph_a = {"nodes": [{"uuid": "node-a", "input": "in", "output": "out", "name": "demo"}]}
    graph_b = {
        "nodes": [
            {"uuid": "node-a", "input": "in", "output": "out", "name": "demo", "model_or_tool": "tool"}
        ]
    }

    assert _graph_fingerprint(graph_a) == _graph_fingerprint(graph_b)


def test_prefetch_futures_are_cached_and_invalidated_per_run(monkeypatch):
    submits: list[str] = []

    class DummyFuture:
        def __init__(self, value: str):
            self._value = value

        def cancelled(self):
            return False

        def done(self):
            return False

        def exception(self):
            return None

        def result(self):
            return self._value

    def fake_submit(fn, trace):
        submits.append(trace.run_id)
        return DummyFuture(f"summary:{trace.run_id}")

    monkeypatch.setattr("sovara.server.graph_analysis.inference_server._pool", SimpleNamespace(submit=fake_submit))
    monkeypatch.setattr("sovara.server.graph_analysis.inference_server._prefetch_futures", {})

    trace = Trace(raw="", records=[], run_id="run-1")

    future_a = _ensure_prefetch_future("run-1", trace, is_new=False)
    future_a_again = _ensure_prefetch_future("run-1", trace, is_new=False)

    assert future_a is future_a_again
    assert submits == ["run-1"]

    trace2 = Trace(raw="", records=[], run_id="run-1")
    _ensure_prefetch_future("run-1", trace2, is_new=True)

    assert submits == ["run-1", "run-1"]


def test_handle_question_does_not_block_on_running_prefetch(monkeypatch):
    class NotReadyFuture:
        def done(self):
            return False

        def result(self):
            raise AssertionError("handle_question should not block on unfinished prefetch")

    def fake_infer(messages, system, tools, max_tokens):
        assert "## Trace Summary" not in system
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="answer", tool_calls=[]))]
        )

    monkeypatch.setattr("sovara.server.graph_analysis.trace_chat.main.infer", fake_infer)

    trace = Trace(raw="", records=[], run_id="run-1")
    result = handle_question("hello", trace, [], prefetch_future=NotReadyFuture())

    assert result == {"answer": "answer", "edits_applied": False}
    assert trace.prefetched_summary == ""



def test_chat_returns_plain_text_upstream_errors_without_crashing(monkeypatch):
    class FakeResponse:
        status_code = 500
        text = "upstream exploded"

        def json(self):
            raise json.JSONDecodeError("Expecting value", "", 0)

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=FakeAsyncClient))

    try:
        asyncio.run(chat("run-1", ChatMessageRequest(message="hello")))
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail == "upstream exploded"


def test_chat_rejects_invalid_json_success_payload(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = "not-json"

        def json(self):
            raise json.JSONDecodeError("Expecting value", "", 0)

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=FakeAsyncClient))

    try:
        asyncio.run(chat("run-1", ChatMessageRequest(message="hello")))
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 502
        assert exc.detail == "Invalid response from inference server"
