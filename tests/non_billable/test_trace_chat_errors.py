import asyncio
import json
import logging
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from sovara.common.logger import create_file_logger
from sovara.server.graph_analysis.inference_server import (
    _ensure_prefetch_future,
    _graph_fingerprint,
    prefetch,
)
from sovara.server.graph_analysis.trace_chat.logger import (
    LOGGER_NAME,
    configure_inference_process_logging,
    ensure_standalone_logger,
    format_log_event_banner,
)
from sovara.server.graph_analysis.trace_chat.main import handle_question
from sovara.server.graph_analysis.trace_chat.tools import execute_tool
from sovara.server.graph_analysis.trace_chat.utils.trace import Trace
from sovara.server.routes.ui import ChatMessageRequest, chat


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


def test_format_log_event_banner_is_single_line_and_parseable():
    banner = format_log_event_banner(
        "User Message [q1]",
        "hello\nthere",
        marker="-",
        min_width=40,
    )

    assert banner.startswith("----")
    assert "\n" not in banner
    assert "USER MESSAGE [Q1]: hello there" in banner


def test_handle_question_logs_user_message_banner(monkeypatch):
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

    assert any("USER MESSAGE" in entry and "hello there" in entry for entry in logs)
    assert any("[trace_chat run_id=run-1 qid=" in entry and "user_message=hello there" in entry for entry in logs)


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


def test_configure_inference_process_logging_routes_agent_logs_to_inference_file(monkeypatch, tmp_path):
    inference_log = tmp_path / "inference_server.log"
    old_log = tmp_path / "agent.log"

    agent_logger = logging.getLogger(LOGGER_NAME)
    previous_handlers = list(agent_logger.handlers)
    previous_level = agent_logger.level
    previous_propagate = agent_logger.propagate

    root_logger = logging.getLogger("Sovara")
    previous_root_handlers = list(root_logger.handlers)
    previous_root_level = root_logger.level

    existing_handler = logging.FileHandler(old_log, mode="a")
    root_handler = logging.StreamHandler()
    root_handler.setLevel(logging.DEBUG)

    try:
        for handler in list(agent_logger.handlers):
            agent_logger.removeHandler(handler)
        agent_logger.addHandler(existing_handler)

        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
        root_logger.addHandler(root_handler)
        root_logger.setLevel(logging.DEBUG)

        monkeypatch.setattr(
            "sovara.server.graph_analysis.trace_chat.logger.INFERENCE_SERVER_LOG",
            str(inference_log),
        )

        configured_logger = configure_inference_process_logging()

        assert configured_logger is agent_logger
        assert configured_logger.level == logging.INFO
        assert configured_logger.propagate is False
        assert len(configured_logger.handlers) == 1
        assert Path(configured_logger.handlers[0].baseFilename) == inference_log.resolve()
        assert Path(configured_logger.handlers[0].baseFilename) != old_log.resolve()
        assert root_logger.level == logging.WARNING
        assert root_handler.level == logging.WARNING
    finally:
        for handler in list(agent_logger.handlers):
            agent_logger.removeHandler(handler)
            handler.close()
        for handler in previous_handlers:
            agent_logger.addHandler(handler)
        agent_logger.setLevel(previous_level)
        agent_logger.propagate = previous_propagate

        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()
        for handler in previous_root_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(previous_root_level)


def test_ensure_standalone_logger_routes_agent_logs_to_inference_file(monkeypatch, tmp_path):
    inference_log = tmp_path / "inference_server.log"
    old_log = tmp_path / "agent.log"

    agent_logger = logging.getLogger(LOGGER_NAME)
    previous_handlers = list(agent_logger.handlers)
    previous_level = agent_logger.level
    previous_propagate = agent_logger.propagate

    existing_handler = logging.FileHandler(old_log, mode="a")

    try:
        for handler in list(agent_logger.handlers):
            agent_logger.removeHandler(handler)
        agent_logger.addHandler(existing_handler)

        monkeypatch.setattr(
            "sovara.server.graph_analysis.trace_chat.logger.INFERENCE_SERVER_LOG",
            str(inference_log),
        )

        configured_logger = ensure_standalone_logger()

        assert configured_logger is agent_logger
        assert configured_logger.level == logging.INFO
        assert configured_logger.propagate is False
        assert len(configured_logger.handlers) == 1
        assert Path(configured_logger.handlers[0].baseFilename) == inference_log.resolve()
        assert Path(configured_logger.handlers[0].baseFilename) != old_log.resolve()
    finally:
        for handler in list(agent_logger.handlers):
            agent_logger.removeHandler(handler)
            handler.close()
        for handler in previous_handlers:
            agent_logger.addHandler(handler)
        agent_logger.setLevel(previous_level)
        agent_logger.propagate = previous_propagate


def test_prefetch_logs_trace_opened_banner(monkeypatch):
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
    assert any("TRACE OPENED: run_id=run-1" in entry for entry in logs)
    assert any(
        "[trace_chat run_id=run-1 source=prefetch] trace_opened steps=0 is_new=True" in entry
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

    try:
        asyncio.run(chat("run-1", ChatMessageRequest(message="hello")))
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 504
        assert exc.detail == "Trace chat timed out after 120 seconds"


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
