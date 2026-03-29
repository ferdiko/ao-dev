import importlib
from types import SimpleNamespace

import pytest

from sovara.server.graph_analysis.trace_chat.tools.ask_step import ask_step
from sovara.server.graph_analysis.trace_chat.tools.get_overview import get_overview
from sovara.server.graph_analysis.trace_chat.tools.get_step import get_step
from sovara.server.graph_analysis.trace_chat.tools.get_summary import get_summary
from sovara.server.graph_analysis.trace_chat.tools.prompt_edit import get_section, insert_section, list_sections, undo
from sovara.server.graph_analysis.trace_chat.tools.verify import verify
from sovara.server.graph_analysis.trace_chat.utils.trace import Trace, TraceRecord, build_trace_record_from_to_show, parse_record


def _seed_stale_analysis(trace: Trace, indices: list[int]) -> None:
    for idx in indices:
        trace.records[idx].summary = f"record summary {idx}"
        trace.records[idx].correct = False
        trace.summary_cache[idx] = f"cached summary {idx}"
        trace.verdict_cache[idx] = ("WRONG", f"cached verdict {idx}")
    trace.prefetched_summary = "stale trace summary"


def test_build_trace_record_from_to_show_uses_flattened_leaf_paths():
    record = build_trace_record_from_to_show(
        {
            "body": {
                "system": "Return JSON only.",
                "messages": [{"role": "user", "content": "Summarize this report."}],
                "temperature": 0.2,
            }
        },
        {"content": {"choices": [{"message": {"content": "done"}}]}},
        index=0,
        name="gpt-4.1-mini",
    )

    assert record.prompt_path == "body.system"
    assert record.message_list_path == "body.messages"
    assert [block.path for block in record.input_blocks] == [
        "body.system",
        "body.messages.0.role",
        "body.messages.0.content",
        "body.temperature",
    ]


def test_trace_record_round_trip_ignores_deprecated_model_kind_fields():
    record = TraceRecord(
        system_prompt="You are concise.",
        input=[{"role": "user", "content": "Hello"}],
        output="ok",
        name="gpt-4.1-mini",
    )

    reparsed = parse_record(record.to_dict(), index=0)

    assert reparsed.name == "gpt-4.1-mini"
    assert "model_or_tool" not in reparsed.to_dict()


def test_trace_chat_overview_and_step_rendering_ignore_deprecated_model_kind_fields():
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {"system_prompt": "Be concise.", "messages": [{"role": "user", "content": "Hello"}]},
            {"output": "Hi"},
            index=0,
            name="gpt-4.1-mini",
        ),
        build_trace_record_from_to_show(
            {"messages": [{"role": "tool", "content": "search results"}]},
            {"output": "done"},
            index=1,
            name="search",
        ),
    ])

    overview = get_overview(trace)
    step = get_step(trace, step_id=1)

    assert "Calls:" not in overview
    assert "[model]" not in overview
    assert "[tool]" not in overview
    assert "Kind:" not in step


def test_parse_record_ignores_deprecated_model_kind_keys():
    parsed = parse_record(
        {
            "system_prompt": "You are concise.",
            "input": [{"role": "user", "content": "Hello"}],
            "output": "ok",
            "name": "demo",
            "model/tool": "tool",
            "model_or_tool": "model",
        },
        index=0,
    )

    assert parsed.name == "demo"
    assert "model_or_tool" not in parsed.to_dict()


def test_prompt_sections_use_flattened_paths_and_paragraph_operations():
    raw = """{"system_prompt":"You are concise.","input":[{"role":"user","content":"First paragraph."}],"output":"ok","name":"demo"}"""
    trace = Trace.from_string(raw)

    table = list_sections(trace, step_id=1)

    assert "`system_prompt`" in table
    assert "`messages.0.content`" in table
    assert "messages.0.role" not in table
    assert "system_prompt::p0" in table

    result = insert_section(
        trace,
        step_id=1,
        path="messages.0.content::p0",
        content="Second paragraph.",
    )
    updated = get_section(trace, step_id=1, path="messages.0.content")
    single = get_section(trace, step_id=1, path="messages.0.content::p1")

    assert "Inserted paragraph" in result
    assert "`messages.0.content::p0`" in updated
    assert "`messages.0.content::p1`" in updated
    assert "`messages.0.content::p1`" in single
    assert single.endswith("Second paragraph.")


def test_prompt_sections_edit_graph_style_flattened_input_paths():
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {
                "body.max_tokens": 100,
                "body.messages": [{"role": "user", "content": "First paragraph."}],
                "body.model": "claude-sonnet-4-6",
            },
            {"content.content": [{"text": "done"}]},
            index=0,
            name="demo",
        )
    ])

    table = list_sections(trace, step_id=1)
    result = insert_section(
        trace,
        step_id=1,
        path="body.messages.0.content::p0",
        content="Second paragraph.",
    )
    updated = get_section(trace, step_id=1, path="body.messages.0.content")

    assert "`body.messages.0.content`" in table
    assert "Inserted paragraph" in result
    assert "`body.messages.0.content::p1`" in updated
    assert updated.endswith("Second paragraph.")


def test_step_edit_invalidates_cached_analysis():
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )
    _seed_stale_analysis(trace, [0])

    insert_section(
        trace,
        step_id=1,
        path="messages.0.content::p0",
        content="Second paragraph.",
    )

    assert trace.records[0].summary is None
    assert trace.records[0].correct is None
    assert trace.diffed[0].summary is None
    assert trace.diffed[0].correct is None
    assert trace.summary_cache == {}
    assert trace.verdict_cache == {}
    assert trace.prefetched_summary == ""


def test_shared_prompt_edit_invalidates_all_steps_using_that_prompt():
    trace = Trace.from_string(
        "\n".join([
            """{"system_prompt":"Shared prompt.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}""",
            """{"system_prompt":"Shared prompt.","input":[{"role":"user","content":"Hello again"}],"output":"ok","name":"demo"}""",
        ])
    )
    _seed_stale_analysis(trace, [0, 1])

    insert_section(
        trace,
        step_id=1,
        path="system_prompt::p0",
        content="Added paragraph.",
    )

    assert trace.records[0].summary is None
    assert trace.records[0].correct is None
    assert trace.records[1].summary is None
    assert trace.records[1].correct is None
    assert trace.diffed[0].summary is None
    assert trace.diffed[0].correct is None
    assert trace.diffed[1].summary is None
    assert trace.diffed[1].correct is None
    assert trace.summary_cache == {}
    assert trace.verdict_cache == {}
    assert trace.prefetched_summary == ""


def test_get_summary_and_verify_do_not_return_stale_values_after_edit(monkeypatch):
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )
    _seed_stale_analysis(trace, [0])
    get_summary_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.get_summary")
    verify_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.verify")

    monkeypatch.setattr(get_summary_module, "infer_text", lambda *args, **kwargs: "fresh summary")
    monkeypatch.setattr(
        verify_module,
        "infer",
        lambda *args, **kwargs: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="<summary>fresh verdict</summary><verdict>CORRECT</verdict>"
                    )
                )
            ]
        ),
    )

    insert_section(
        trace,
        step_id=1,
        path="messages.0.content::p0",
        content="Second paragraph.",
    )

    assert get_summary(trace, step_id=1) == "Step 1 summary:\nfresh summary"
    assert verify(trace, step_id=1) == "Step 1: CORRECT\n  fresh verdict"


def test_read_tools_share_step_id_validation_messages():
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )

    expected_type = "Error: 'step_id' must be an integer, got 'abc'."
    expected_range = "Error: step_id 2 out of range (1–1)."

    assert get_step(trace, step_id="abc") == expected_type
    assert get_summary(trace, step_id="abc") == expected_type
    assert ask_step(trace, step_id="abc", question="hi") == expected_type
    assert verify(trace, step_id="abc") == expected_type

    assert get_step(trace, step_id=2) == expected_range
    assert get_summary(trace, step_id=2) == expected_range
    assert ask_step(trace, step_id=2, question="hi") == expected_range
    assert verify(trace, step_id=2) == expected_range
