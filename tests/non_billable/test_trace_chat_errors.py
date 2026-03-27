import asyncio
import json
import sys
import types
from types import SimpleNamespace

from fastapi import HTTPException

from sovara.server.graph_analysis.inference_server import _ensure_prefetch_future, _graph_fingerprint
from sovara.server.graph_analysis.trace_chat.main import handle_question
from sovara.server.graph_analysis.trace_chat.tools.summarize_trace import summarize_trace
from sovara.server.graph_analysis.trace_chat.utils.trace import Trace
from sovara.server.routes.ui import ChatMessageRequest, chat


def test_graph_fingerprint_accepts_uuid_shaped_nodes():
    graph_data = {"nodes": [{"uuid": "node-a", "input": "in", "output": "out"}]}
    legacy_graph_data = {"nodes": [{"id": "node-a", "input": "in", "output": "out"}]}

    assert _graph_fingerprint(graph_data) == _graph_fingerprint(legacy_graph_data)


def test_prefetch_futures_are_cached_per_model_and_invalidated_per_run(monkeypatch):
    submits: list[tuple[str, str]] = []

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

    def fake_submit(fn, trace, model):
        submits.append((trace.run_id, model))
        return DummyFuture(f"summary:{trace.run_id}:{model}")

    monkeypatch.setattr("sovara.server.graph_analysis.inference_server._pool", SimpleNamespace(submit=fake_submit))
    monkeypatch.setattr("sovara.server.graph_analysis.inference_server._prefetch_futures", {})

    trace = Trace(raw="", records=[], run_id="run-1")

    future_a = _ensure_prefetch_future("run-1", trace, "model-a", is_new=False)
    future_b = _ensure_prefetch_future("run-1", trace, "model-b", is_new=False)
    future_a_again = _ensure_prefetch_future("run-1", trace, "model-a", is_new=False)

    assert future_a is future_a_again
    assert future_a is not future_b
    assert submits == [("run-1", "model-a"), ("run-1", "model-b")]

    trace2 = Trace(raw="", records=[], run_id="run-1")
    _ensure_prefetch_future("run-1", trace2, "model-a", is_new=True)

    assert submits == [("run-1", "model-a"), ("run-1", "model-b"), ("run-1", "model-a")]


def test_handle_question_does_not_block_on_running_prefetch(monkeypatch):
    class NotReadyFuture:
        def done(self):
            return False

        def result(self):
            raise AssertionError("handle_question should not block on unfinished prefetch")

    def fake_infer(messages, model, system, tools, max_tokens):
        assert "## Trace Summary" not in system
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="answer", tool_calls=[]))]
        )

    monkeypatch.setattr("sovara.server.graph_analysis.trace_chat.main.infer", fake_infer)

    trace = Trace(raw="", records=[], run_id="run-1")
    result = handle_question("hello", trace, [], "model-a", prefetch_future=NotReadyFuture())

    assert result == {"answer": "answer", "edits_applied": False}
    assert trace.prefetched_summaries == {}


def test_summarize_trace_cache_is_model_specific(monkeypatch):
    calls: list[str] = []

    def fake_generate_summary(trace, model):
        calls.append(model)
        return f"summary:{model}"

    monkeypatch.setattr(
        "sovara.server.graph_analysis.trace_chat.tools.summarize_trace._generate_summary",
        fake_generate_summary,
    )

    trace = Trace(raw="", records=[])
    trace.prefetched_summaries["model-a"] = "prefetched-a"

    assert summarize_trace(trace, model="model-a") == "prefetched-a"
    assert summarize_trace(trace, model="model-b") == "summary:model-b"
    assert calls == ["model-b"]


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
