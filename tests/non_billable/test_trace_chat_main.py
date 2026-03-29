import subprocess
import sys
from pathlib import Path

from sovara.server.graph_analysis.trace_chat import main as trace_chat_main


def test_trace_chat_main_loads_trace_and_uses_input(monkeypatch, capsys, tmp_path):
    trace_path = tmp_path / "weather_agent.jsonl"
    trace_path.write_text(
        '{"system_prompt":"prompt","input":[{"role":"user","content":"hi"}],"output":"ok"}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(trace_chat_main, "ensure_standalone_logger", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "quit")

    trace_chat_main.main(["--no-prefetch", str(trace_path)])

    out = capsys.readouterr().out
    assert f"Loading trace from {trace_path.resolve()}" in out
    assert "Loaded 1 steps." in out
    assert "Chat started. Type 'quit' to exit." in out
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
