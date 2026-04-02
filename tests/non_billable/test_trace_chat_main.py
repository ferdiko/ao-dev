import subprocess
import sys
from pathlib import Path

from sovara.server.graph_analysis.trace_chat import main as trace_chat_main
from sovara.server.graph_analysis.trace_chat.utils.trace import Trace


def test_trace_chat_main_loads_trace_and_uses_input(monkeypatch, capsys, tmp_path):
    trace_path = tmp_path / "weather_agent.jsonl"
    trace_path.write_text(
        '{"system_prompt":"prompt","input":[{"role":"user","content":"hi"}],"output":"ok"}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "quit")

    trace_chat_main.main(["--no-prefetch", str(trace_path)])

    out = capsys.readouterr().out
    assert "Goodbye!" in out


def test_trace_chat_main_uses_default_trace_relative_to_module(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "quit")

    trace_chat_main.main(["--no-prefetch"], default_trace_path="example_traces/weather_agent.jsonl")

    out = capsys.readouterr().out
    assert "Goodbye!" in out


def test_trace_chat_main_help_works_as_standalone_script():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "src/sovara/server/graph_analysis/trace_chat/main.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Interactive trace chat debugger for JSONL traces." in result.stdout
    assert "trace_path" in result.stdout


def test_start_prefetch_logs_requested_start(monkeypatch):
    calls = []

    class DummyFuture:
        pass

    class FakePool:
        def __init__(self, max_workers):
            assert max_workers == 1
            self.future = DummyFuture()

        def submit(self, fn, trace):
            assert fn is trace_chat_main._generate_summary
            assert trace.run_id == "run-1"
            return self.future

    class FakeLogger:
        def info(self, message, *args):
            calls.append((message, args))

    monkeypatch.setattr(trace_chat_main, "ThreadPoolExecutor", FakePool)
    monkeypatch.setattr(trace_chat_main, "logger", FakeLogger())

    pool, future = trace_chat_main._start_prefetch(Trace(raw="", records=[], run_id="run-1"), enabled=True)

    assert future is pool.future
    assert hasattr(future, "_sovara_started_at")
    assert calls == [("Trace chat prefetch requested from main run_id=%s steps=%d", ("run-1", 0))]
