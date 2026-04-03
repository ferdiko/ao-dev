import asyncio
import importlib
import json
import logging
import os
import sys
import threading
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from sovara.common.logger import create_file_logger
from sovara.server.database import DB
from sovara.server.graph_analysis.inference_server import (
    _ensure_prefetch_future,
    _graph_fingerprint,
    prefetch,
)
from sovara.server.graph_analysis.trace_chat.cancel import TraceChatCancelled
from sovara.server.graph_analysis.trace_chat.main import handle_question
from sovara.server.graph_analysis.trace_chat.tools import execute_tool
from sovara.server.graph_analysis.trace_chat.utils.edit_persist import DISPLAY_ONLY_MSG
from sovara.server.graph_analysis.trace_chat.utils.trace import Trace
from sovara.server.routes.ui import ChatMessageRequest, chat
from sovara.server.state import ServerState


def _create_trace_chat_run() -> tuple[str, str]:
    project_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    DB.upsert_project(project_id, "trace-chat-project", "")
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
    return project_id, run_id


def test_graph_fingerprint_accepts_uuid_shaped_nodes():
    graph_data = {"nodes": [{"uuid": "node-a", "input": "in", "output": "out"}]}
    legacy_graph_data = {"nodes": [{"id": "node-a", "input": "in", "output": "out"}]}

    assert _graph_fingerprint(graph_data) == _graph_fingerprint(legacy_graph_data)


def test_graph_fingerprint_ignores_unrelated_extra_keys():
    graph_a = {"nodes": [{"uuid": "node-a", "input": "in", "output": "out", "name": "demo"}]}
    graph_b = {
        "nodes": [
            {"uuid": "node-a", "input": "in", "output": "out", "name": "demo", "ignored": "value"}
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


def test_handle_question_raises_when_cancelled_before_iteration(monkeypatch):
    infer_called = [False]

    def fake_infer(messages, system, tools, max_tokens):
        infer_called[0] = True
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="answer", tool_calls=[]))]
        )

    cancel_event = threading.Event()
    cancel_event.set()
    monkeypatch.setattr("sovara.server.graph_analysis.trace_chat.main.infer", fake_infer)

    with pytest.raises(TraceChatCancelled):
        handle_question("hello", Trace(raw="", records=[], run_id="run-1"), [], cancel_event=cancel_event)

    assert infer_called == [False]


def test_handle_question_logs_question_start(monkeypatch):
    logs: list[str] = []

    def fake_infer(messages, system, tools, max_tokens):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="answer", tool_calls=[]))]
        )

    class FakeLogger:
        def info(self, message, *args):
            logs.append(message % args if args else message)

        def warning(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

        def debug(self, *args, **kwargs):
            return None

    monkeypatch.setattr("sovara.server.graph_analysis.trace_chat.main.infer", fake_infer)
    monkeypatch.setattr("sovara.server.graph_analysis.trace_chat.main.logger", FakeLogger())

    handle_question("hello there", Trace(raw="", records=[], run_id="run-1"), [])

    assert any(
        "Trace chat question start run_id=run-1 qid=" in entry and "message=hello there" in entry
        for entry in logs
    )
    assert any(
        "Trace chat context run_id=run-1 qid=" in entry and "history_messages=0" in entry
        for entry in logs
    )


def test_handle_question_logs_llm_exceptions(monkeypatch):
    calls: list[tuple[str, tuple[object, ...]]] = []

    def fake_infer(messages, system, tools, max_tokens):
        raise RuntimeError("llm exploded")

    class FakeLogger:
        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def exception(self, message, *args):
            calls.append((message, args))

    monkeypatch.setattr("sovara.server.graph_analysis.trace_chat.main.infer", fake_infer)
    monkeypatch.setattr("sovara.server.graph_analysis.trace_chat.main.logger", FakeLogger())

    try:
        handle_question("hello", Trace(raw="", records=[], run_id="run-1"), [])
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert str(exc) == "llm exploded"

    assert calls == [("LLM call failed on iteration %d", (1,))]


def test_handle_question_returns_immediately_after_successful_edit_tool(monkeypatch):
    infer_calls = [0]

    def fake_infer(messages, system, tools, max_tokens):
        infer_calls[0] += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        tool_calls=[
                            SimpleNamespace(
                                id="call-1",
                                function=SimpleNamespace(
                                    name="edit_content",
                                    arguments='{"step_id": 1, "content_id": "c0", "instruction": "rewrite"}',
                                ),
                            )
                        ],
                    )
                )
            ]
        )

    monkeypatch.setattr("sovara.server.graph_analysis.trace_chat.main.infer", fake_infer)
    monkeypatch.setattr(
        "sovara.server.graph_analysis.trace_chat.main.execute_tool",
        lambda name, trace, params, log_tag=None: "Edited content.\n\nEdit applied and saved.",
    )

    result = handle_question("rewrite it", Trace(raw="", records=[], run_id="run-1"), [])

    assert infer_calls == [1]
    assert result == {
        "answer": "Edited content.\n\nEdit applied and saved.",
        "edits_applied": True,
    }


def test_handle_question_returns_immediately_after_display_only_edit_tool(monkeypatch):
    infer_calls = [0]

    def fake_infer(messages, system, tools, max_tokens):
        infer_calls[0] += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        tool_calls=[
                            SimpleNamespace(
                                id="call-1",
                                function=SimpleNamespace(
                                    name="edit_content",
                                    arguments='{"step_id": 1, "content_id": "c5", "instruction": "rewrite"}',
                                ),
                            )
                        ],
                    )
                )
            ]
        )

    monkeypatch.setattr("sovara.server.graph_analysis.trace_chat.main.infer", fake_infer)
    monkeypatch.setattr(
        "sovara.server.graph_analysis.trace_chat.main.execute_tool",
        lambda name, trace, params, log_tag=None: f"Edited content.{DISPLAY_ONLY_MSG}",
    )

    result = handle_question("rewrite it", Trace(raw="", records=[], run_id="run-1"), [])

    assert infer_calls == [1]
    assert result == {
        "answer": f"Edited content.{DISPLAY_ONLY_MSG}",
        "edits_applied": False,
    }


def test_scatter_execute_returns_none_for_exception_and_timeout(monkeypatch):
    llm_backend = importlib.import_module("sovara.server.llm_backend")
    pool_state: dict[str, object] = {}
    wait_calls = [0]

    class FakeFuture:
        def __init__(self, *, value=None, error=None):
            self._value = value
            self._error = error

        def result(self):
            if self._error is not None:
                raise self._error
            return self._value

    success_future = FakeFuture(value="ok")
    failure_future = FakeFuture(error=RuntimeError("boom"))
    timeout_future = FakeFuture(value="late")

    class FakePool:
        def __init__(self, max_workers):
            pool_state["max_workers"] = max_workers
            pool_state["shutdown_calls"] = []

        def submit(self, fn, item):
            return {1: success_future, 2: failure_future, 3: timeout_future}[item]

        def shutdown(self, wait=False, cancel_futures=False):
            pool_state["shutdown_calls"].append((wait, cancel_futures))

    def fake_wait(futures, timeout, return_when):
        wait_calls[0] += 1
        if wait_calls[0] == 1:
            return ({success_future, failure_future}, {timeout_future})
        return (set(), set(futures))

    seen_results: list[tuple[int, str]] = []
    seen_exceptions: list[tuple[int, str]] = []
    seen_timeouts: list[int] = []

    monkeypatch.setattr(llm_backend, "ThreadPoolExecutor", FakePool)
    monkeypatch.setattr(llm_backend, "wait", fake_wait)

    results = llm_backend.scatter_execute(
        [1, 2, 3],
        lambda item: item,
        max_workers=2,
        on_result=lambda item, result: seen_results.append((item, result)),
        on_exception=lambda item, exc: seen_exceptions.append((item, str(exc))),
        on_timeout=lambda items: seen_timeouts.extend(items),
    )

    assert results == ["ok", None, None]
    assert seen_results == [(1, "ok")]
    assert seen_exceptions == [(2, "boom")]
    assert seen_timeouts == [3]
    assert pool_state["max_workers"] == 2
    assert pool_state["shutdown_calls"] == [(False, True)]


def test_scatter_execute_raises_when_cancelled():
    llm_backend = importlib.import_module("sovara.server.llm_backend")
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(TraceChatCancelled):
        llm_backend.scatter_execute([1], lambda item: item, cancel_event=cancel_event)


def test_create_file_logger_can_rebind_named_logger(tmp_path):
    log_a = tmp_path / "a.log"
    log_b = tmp_path / "b.log"
    logger_name = "sovara.test.named_logger"

    named_logger = logging.getLogger(logger_name)
    previous_handlers = list(named_logger.handlers)
    previous_level = named_logger.level
    previous_propagate = named_logger.propagate

    try:
        for handler in list(named_logger.handlers):
            named_logger.removeHandler(handler)

        first = create_file_logger(str(log_a), logger_name=logger_name, level=logging.INFO)
        second = create_file_logger(
            str(log_b),
            logger_name=logger_name,
            level=logging.WARNING,
            replace_handlers=True,
        )

        assert first is named_logger
        assert second is named_logger
        assert named_logger.level == logging.WARNING
        assert named_logger.propagate is False
        assert len(named_logger.handlers) == 1
        assert Path(named_logger.handlers[0].baseFilename) == log_b.resolve()
    finally:
        for handler in list(named_logger.handlers):
            named_logger.removeHandler(handler)
            handler.close()
        for handler in previous_handlers:
            named_logger.addHandler(handler)
        named_logger.setLevel(previous_level)
        named_logger.propagate = previous_propagate


def test_prefetch_logs_trace_opened(monkeypatch):
    logs: list[str] = []
    trace = Trace(raw="", records=[], run_id="run-1")

    class FakeLogger:
        def info(self, message, *args):
            logs.append(message % args if args else message)

        def warning(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

    class FakePool:
        def submit(self, fn):
            fn()
            return SimpleNamespace()

    monkeypatch.setattr(
        "sovara.server.graph_analysis.inference_server._get_trace_for_run",
        lambda run_id: (trace, True),
    )
    monkeypatch.setattr(
        "sovara.server.graph_analysis.inference_server._ensure_prefetch_future",
        lambda run_id, trace, is_new: object(),
    )
    monkeypatch.setattr("sovara.server.graph_analysis.inference_server._pool", FakePool())
    monkeypatch.setattr("sovara.server.graph_analysis.inference_server.logger", FakeLogger())

    assert prefetch("run-1") == {"status": "prefetching"}
    assert any(
        "Trace chat opened from prefetch run_id=run-1 steps=0 is_new=True" in entry
        for entry in logs
    )


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

    project_id, run_id = _create_trace_chat_run()
    try:
        asyncio.run(chat(run_id, ChatMessageRequest(message="hello"), ServerState()))
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail == "upstream exploded"
    finally:
        DB.delete_project(project_id)


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

    project_id, run_id = _create_trace_chat_run()
    try:
        asyncio.run(chat(run_id, ChatMessageRequest(message="hello"), ServerState()))
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 502
        assert exc.detail == "Invalid response from inference server"
    finally:
        DB.delete_project(project_id)


def test_chat_returns_gateway_timeout_when_inference_proxy_times_out(monkeypatch):
    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise TimeoutError("slow")

    monkeypatch.setitem(
        sys.modules,
        "httpx",
        types.SimpleNamespace(
            AsyncClient=FakeAsyncClient,
            TimeoutException=TimeoutError,
            HTTPError=Exception,
        ),
    )

    project_id, run_id = _create_trace_chat_run()
    try:
        asyncio.run(chat(run_id, ChatMessageRequest(message="hello"), ServerState()))
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 504
        assert exc.detail == "Trace chat timed out after 120 seconds"
    finally:
        DB.delete_project(project_id)


def test_execute_tool_logs_exceptions(monkeypatch):
    calls: list[tuple[str, tuple[object, ...]]] = []

    def boom(trace, **params):
        raise KeyError("body")

    class FakeLogger:
        def exception(self, message, *args):
            calls.append((message, args))

    monkeypatch.setitem(sys.modules["sovara.server.graph_analysis.trace_chat.tools"].TOOL_FUNCTIONS, "boom", boom)
    monkeypatch.setattr("sovara.server.graph_analysis.trace_chat.tools.server_logger", FakeLogger())

    result = execute_tool("boom", Trace(raw="", records=[]), {"path": "body.messages.0.content"})

    assert result == "Tool 'boom' failed: 'body'"
    assert calls == [("Trace chat tool failed: %s params=%s", ("boom", {"path": "body.messages.0.content"}))]
