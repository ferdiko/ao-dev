import importlib
from types import SimpleNamespace

import pytest

from sovara.server.graph_analysis.trace_chat.tools.ask_step import ask_step
from sovara.server.graph_analysis.trace_chat.tools.get_trace_overview import get_trace_overview
from sovara.server.graph_analysis.trace_chat.tools.get_step import get_step
from sovara.server.graph_analysis.trace_chat.tools.get_step_overview import get_step_overview
from sovara.server.graph_analysis.trace_chat.tools.prompt_edit import (
    delete_content_paragraph,
    edit_content,
    get_content,
    insert_content_paragraph,
    move_content_paragraph,
    list_sections,
    undo,
)
from sovara.server.graph_analysis.trace_chat.tools.verify import verify
from sovara.server.graph_analysis.trace_chat.utils.trace import (
    Trace,
    TraceRecord,
    blocks_char_count,
    build_trace_record_from_to_show,
    parse_record,
)


def _seed_stale_analysis(trace: Trace, indices: list[int]) -> None:
    for idx in indices:
        trace.records[idx].summary = f"record summary {idx}"
        trace.records[idx].correct = False
        trace.summary_cache[idx] = f"cached summary {idx}"
        trace.step_overview_cache[idx] = f"cached step overview {idx}"
        trace.step_semantic_summary_cache[idx] = f"cached semantic summary {idx}"
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


def test_trace_record_round_trip_preserves_current_fields():
    record = TraceRecord(
        system_prompt="You are concise.",
        input=[{"role": "user", "content": "Hello"}],
        output="ok",
        name="gpt-4.1-mini",
    )

    reparsed = parse_record(record.to_dict(), index=0)

    assert reparsed.name == "gpt-4.1-mini"
    assert reparsed.to_dict() == {
        "system_prompt": "You are concise.",
        "input": [{"role": "user", "content": "Hello"}],
        "output": "ok",
        "correct": None,
        "label": None,
        "summary": None,
        "name": "gpt-4.1-mini",
    }


def test_trace_chat_overview_and_step_rendering_omit_kind_metadata():
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

    overview = get_trace_overview(trace)
    step = get_step(trace, step_id=1)

    assert "Calls:" not in overview
    assert "[model]" not in overview
    assert "[tool]" not in overview
    assert "Kind:" not in step


def test_get_step_full_returns_raw_multiline_prompt_text():
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {
                "body": {
                    "system": "Line 1\n\nLine 2\n\n## Heading\n\nBody text",
                    "messages": [{"role": "user", "content": "Alpha\n\nBeta"}],
                }
            },
            {"output": "Result line 1\n\nResult line 2"},
            index=0,
            name="demo",
        )
    ])

    result = get_step(trace, step_id=1, view="full")

    assert "Paragraph 1:" not in result
    assert "Summary:" not in result
    assert "Line 1\n\nLine 2\n\n## Heading\n\nBody text" in result
    assert "Alpha\n\nBeta" in result
    assert "Result line 1\n\nResult line 2" in result


def test_get_step_diff_and_output_preserve_raw_text():
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {"messages": [{"role": "user", "content": "First line\n\nSecond line"}]},
            {"output": "Output line 1\n\nOutput line 2"},
            index=0,
            name="demo",
        )
    ])

    diff_result = get_step(trace, step_id=1, view="diff")
    output_result = get_step(trace, step_id=1, view="output")

    assert "Paragraph 1:" not in diff_result
    assert "Summary:" not in diff_result
    assert "First line\n\nSecond line" in diff_result
    assert "Paragraph 1:" not in output_result
    assert "Summary:" not in output_result
    assert "Output line 1\n\nOutput line 2" in output_result


def test_parse_record_ignores_unknown_extra_keys():
    parsed = parse_record(
        {
            "system_prompt": "You are concise.",
            "input": [{"role": "user", "content": "Hello"}],
            "output": "ok",
            "name": "demo",
            "ignored": "value",
        },
        index=0,
    )

    assert parsed.name == "demo"
    assert parsed.to_dict() == {
        "system_prompt": "You are concise.",
        "input": [{"role": "user", "content": "Hello"}],
        "output": "ok",
        "correct": None,
        "label": None,
        "summary": None,
        "name": "demo",
    }


def test_prompt_sections_use_flattened_paths_and_paragraph_operations():
    raw = """{"system_prompt":"You are concise.","input":[{"role":"user","content":"First paragraph."}],"output":"ok","name":"demo"}"""
    trace = Trace.from_string(raw)

    table = list_sections(trace, step_id=1)

    assert "`system_prompt`" in table
    assert "`messages.0.content`" in table
    assert "messages.0.role" not in table
    assert "system_prompt::p0" in table

    result = insert_content_paragraph(
        trace,
        step_id=1,
        path="messages.0.content::p0",
        content="Second paragraph.",
    )
    updated = get_content(trace, step_id=1, path="messages.0.content")
    single = get_content(trace, step_id=1, path="messages.0.content::p1")

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
    result = insert_content_paragraph(
        trace,
        step_id=1,
        path="body.messages.0.content::p0",
        content="Second paragraph.",
    )
    updated = get_content(trace, step_id=1, path="body.messages.0.content")

    assert "`body.messages.0.content`" in table
    assert "Inserted paragraph" in result
    assert "`body.messages.0.content::p1`" in updated
    assert updated.endswith("Second paragraph.")


def test_step_edit_invalidates_cached_analysis():
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )
    _seed_stale_analysis(trace, [0])

    insert_content_paragraph(
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
    assert trace.step_overview_cache == {}
    assert trace.step_semantic_summary_cache == {}
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

    insert_content_paragraph(
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
    assert trace.step_overview_cache == {}
    assert trace.step_semantic_summary_cache == {}
    assert trace.verdict_cache == {}
    assert trace.prefetched_summary == ""


def test_get_step_overview_and_verify_do_not_return_stale_values_after_edit(monkeypatch):
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )
    _seed_stale_analysis(trace, [0])
    verify_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.verify")
    step_overview_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.get_step_overview"
    )

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
    monkeypatch.setattr(
        step_overview_module,
        "infer_text",
        lambda messages, **kwargs: (
            "General task and output. Specific input details. Specific output details."
            if messages[0]["content"] == step_overview_module.STEP_SUMMARIZE_SYSTEM
            else "hello content"
        ),
    )

    insert_content_paragraph(
        trace,
        step_id=1,
        path="messages.0.content::p0",
        content="Second paragraph.",
    )

    summary = get_step_overview(trace, step_id=1)

    assert "cached step overview 0" not in summary
    assert "## Three-Sentence Summary" in summary
    assert "## Input Content" in summary
    assert "`messages.0.content`" in summary
    assert "content_id=c0" in summary
    assert verify(trace, step_id=1) == "Step 1: CORRECT\n  fresh verdict"


def test_get_step_full_returns_compact_preview_for_large_steps(monkeypatch):
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {
                "body": {
                    "messages": [
                        {"role": "user", "content": "Intro sentence. " + ("very long content " * 80)}
                    ]
                }
            },
            {"output": "ok"},
            index=0,
            name="demo",
        )
    ])
    trace.step_overview_cache[0] = "\n".join([
        "# Step 1",
        "Name: demo",
        "",
        "## Three-Sentence Summary",
        "",
        "General task and output. Specific input details. Specific output details.",
        "",
        "## Input Content",
        "",
        "### `body.messages.0.content` [user]",
        "- `content_id=c0` summarized content (1520 chars): very long content summary",
    ])
    get_step_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.get_step")
    monkeypatch.setattr(get_step_module, "MAX_FULL_STEP_CHARS", 80)

    result = get_step(trace, step_id=1, view="full")
    record = trace.get(0)

    assert "Step 1 is too long to load inline in requested `full` view" in result
    assert (
        f"({blocks_char_count(record.input_blocks)} input chars, "
        f"{blocks_char_count(record.output_blocks)} output chars)."
    ) in result
    assert "Showing `get_step_overview` instead:" in result
    assert "`get_content(step_id=1, path=\"...\", content_id=\"...\")`" in result
    assert "`get_step(step_id=1, view=\"diff\")`" in result
    assert "`get_step(step_id=1, view=\"output\")`" in result
    assert "very long content " * 80 not in result
    assert "`body.messages.0.content`" in result


def test_get_step_diff_returns_compact_preview_for_large_steps(monkeypatch):
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {
                "body": {
                    "messages": [
                        {"role": "user", "content": "Intro sentence. " + ("very long content " * 80)}
                    ]
                }
            },
            {"output": "ok"},
            index=0,
            name="demo",
        )
    ])
    trace.step_overview_cache[0] = "\n".join([
        "# Step 1",
        "Name: demo",
        "",
        "## Three-Sentence Summary",
        "",
        "General task and output. Specific input details. Specific output details.",
        "",
        "## Input Content",
        "",
        "### `body.messages.0.content` [user]",
        "- `content_id=c0` summarized content (1520 chars): very long content summary",
    ])
    get_step_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.get_step")
    monkeypatch.setattr(get_step_module, "MAX_FULL_STEP_CHARS", 80)

    result = get_step(trace, step_id=1, view="diff")
    record = trace.get(0)

    assert "Step 1 is too long to load inline in requested `diff` view" in result
    assert (
        f"({blocks_char_count(record.input_blocks)} input chars, "
        f"{blocks_char_count(record.output_blocks)} output chars)."
    ) in result
    assert "Showing `get_step_overview` instead:" in result
    assert "`get_content(step_id=1, path=\"...\", content_id=\"...\")`" in result
    assert "`get_step(step_id=1, view=\"diff\")`" in result
    assert "`get_step(step_id=1, view=\"output\")`" in result
    assert "very long content " * 80 not in result
    assert "`body.messages.0.content`" in result


def test_get_step_overview_returns_structured_overview_for_large_steps(monkeypatch):
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {
                "body": {
                    "messages": [
                        {"role": "user", "content": "Intro sentence. " + ("very long content " * 80)}
                    ]
                }
            },
            {"output": "ok"},
            index=0,
            name="demo",
        )
    ])
    step_overview_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.get_step_overview"
    )

    def fake_infer_text(messages, **kwargs):
        system = messages[0]["content"]
        if system == step_overview_module.STEP_SUMMARIZE_SYSTEM:
            return "General task and output. Specific input details. Specific output details."
        return "long content summary"

    monkeypatch.setattr(step_overview_module, "infer_text", fake_infer_text)

    summary = get_step_overview(trace, step_id=1)

    assert "# Step 1" in summary
    assert "## Three-Sentence Summary" in summary
    assert "## Input Content" in summary
    assert "content_id=c0" in summary
    assert "long content summary" in summary
    assert "very long content " * 80 not in summary


def test_get_step_overview_shows_content_id_for_inline_short_content(monkeypatch):
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {"body": {"messages": [{"role": "user", "content": "Short content."}]}},
            {"output": "ok"},
            index=0,
            name="demo",
        )
    ])
    step_overview_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.get_step_overview"
    )

    monkeypatch.setattr(
        step_overview_module,
        "infer_text",
        lambda messages, **kwargs: "General task and output. Specific input details. Specific output details.",
    )

    summary = get_step_overview(trace, step_id=1)

    assert "content_id=c0" in summary
    assert "full content" in summary
    assert "Short content." in summary


def test_get_content_expands_content_by_content_id(monkeypatch):
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {
                "body": {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "First paragraph is intentionally long enough to require summarization. "
                                "It keeps going for a while.\n\n"
                                "Second paragraph is also long enough to be summarized separately. "
                                "It also keeps going."
                            ),
                        }
                    ]
                }
            },
            {"output": "ok"},
            index=0,
            name="demo",
        )
    ])
    step_overview_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.get_step_overview"
    )

    def fake_infer_text(messages, **kwargs):
        system = messages[0]["content"]
        if system == step_overview_module.STEP_SUMMARIZE_SYSTEM:
            return "General task and output. Specific input details. Specific output details."
        return "i0\tFirst paragraph summary\ni1\tSecond paragraph summary"

    monkeypatch.setattr(step_overview_module, "infer_text", fake_infer_text)

    summary = get_step_overview(trace, step_id=1)
    expanded = get_content(trace, step_id=1, path="body.messages.0.content", content_id="c1")

    assert "content_id=c0" in summary
    assert "content_id=c1" in summary
    assert "Second paragraph summary" in summary
    assert "Second paragraph is also long enough to be summarized separately." in expanded


def test_edit_content_accepts_content_id(monkeypatch):
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {
                "body": {
                    "messages": [
                        {
                            "role": "user",
                            "content": "First paragraph.\n\nSecond paragraph that should be edited.",
                        }
                    ]
                }
            },
            {"output": "ok"},
            index=0,
            name="demo",
        )
    ])
    prompt_edit_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.prompt_edit"
    )

    monkeypatch.setattr(prompt_edit_module, "infer_text", lambda *args, **kwargs: "Edited second paragraph.")

    result = edit_content(
        trace,
        step_id=1,
        path="body.messages.0.content",
        content_id="c1",
        instruction="Rewrite this paragraph.",
    )
    updated = get_content(trace, step_id=1, path="body.messages.0.content", content_id="c1")

    assert "content_id=c1" in result
    assert updated.endswith("Edited second paragraph.")


def test_paragraph_structure_tools_accept_content_id(monkeypatch):
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {
                "body": {
                    "messages": [
                        {
                            "role": "user",
                            "content": "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.",
                        }
                    ]
                }
            },
            {"output": "ok"},
            index=0,
            name="demo",
        )
    ])

    inserted = insert_content_paragraph(
        trace,
        step_id=1,
        path="body.messages.0.content",
        after_content_id="c0",
        content="Inserted after first paragraph.",
    )
    moved = move_content_paragraph(
        trace,
        step_id=1,
        path="body.messages.0.content",
        from_content_id="c2",
        to_paragraph=0,
    )
    deleted = delete_content_paragraph(
        trace,
        step_id=1,
        path="body.messages.0.content",
        content_id="c1",
    )

    assert "Inserted paragraph" in inserted
    assert "Moved" in moved
    assert "Deleted" in deleted


def test_tool_registry_exposes_get_step_overview():
    tools_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools")

    assert "get_step_overview" in tools_module.TOOL_FUNCTIONS
    assert "get_content" in tools_module.TOOL_FUNCTIONS
    assert "insert_content_paragraph" in tools_module.TOOL_FUNCTIONS
    assert "delete_content_paragraph" in tools_module.TOOL_FUNCTIONS
    assert "move_content_paragraph" in tools_module.TOOL_FUNCTIONS
    assert any(tool["function"]["name"] == "get_step_overview" for tool in tools_module.TOOLS_SCHEMA)
    assert any(tool["function"]["name"] == "get_content" for tool in tools_module.TOOLS_SCHEMA)


def test_summarize_trace_keeps_internal_three_sentence_step_summaries(monkeypatch):
    trace = Trace.from_string(
        "\n".join([
            """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}""",
            """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello again"}],"output":"done","name":"demo"}""",
        ])
    )
    summarize_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.summarize_trace")
    step_overview_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.get_step_overview"
    )
    calls: list[tuple[str, str]] = []

    def fake_infer_text(messages, **kwargs):
        system = messages[0]["content"]
        user = messages[1]["content"]
        calls.append((system, user))
        if system == summarize_module.STEP_SUMMARIZE_SYSTEM:
            return "Sentence one. Sentence two. Sentence three."
        return "Trace summary"

    monkeypatch.setattr(summarize_module, "infer_text", fake_infer_text)
    monkeypatch.setattr(step_overview_module, "infer_text", fake_infer_text)

    result = summarize_module.summarize_trace(trace)

    assert result == "Trace summary"
    assert any(system == summarize_module.STEP_SUMMARIZE_SYSTEM for system, _user in calls)
    assert any(
        system == summarize_module.SYNTHESIZE_SYSTEM and "Sentence one. Sentence two. Sentence three." in user
        for system, user in calls
    )


def test_generate_summary_logs_prefetch_tagged_progress(monkeypatch):
    trace = Trace.from_string(
        "\n".join([
            """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}""",
            """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello again"}],"output":"done","name":"demo"}""",
        ])
    )
    trace.run_id = "run-1"
    summarize_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.summarize_trace")
    logs: list[tuple[str, tuple[object, ...]]] = []

    class FakeLogger:
        def info(self, message, *args):
            logs.append((message, args))

        def exception(self, message, *args):
            logs.append((message, args))

    monkeypatch.setattr(summarize_module, "get_trace_overview", lambda trace: "overview")
    monkeypatch.setattr(
        summarize_module,
        "get_or_compute_step_semantic_summary",
        lambda trace, step_id: f"semantic summary {step_id}",
    )
    monkeypatch.setattr(summarize_module, "infer_text", lambda messages, **kwargs: "Trace summary")
    monkeypatch.setattr(summarize_module, "logger", FakeLogger())

    result = summarize_module._generate_summary(trace)

    assert result == "Trace summary"
    assert logs[0] == ("%s start steps=%d", ("[prefetch run_id=run-1]", 2))
    assert any(
        message == "%s semantic summary ready in %.1fs chars=%d"
        and args[0].startswith("[prefetch run_id=run-1 phase=step")
        for message, args in logs
    )
    assert any(
        message == "%s done summary_chars=%d per_step=%.1fs synthesis=%.1fs total=%.1fs"
        and args[0] == "[prefetch run_id=run-1]"
        for message, args in logs
    )


def test_read_tools_share_step_id_validation_messages():
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )

    expected_type = "Error: 'step_id' must be an integer, got 'abc'."
    expected_range = "Error: step_id 2 out of range (1–1)."

    assert get_step(trace, step_id="abc") == expected_type
    assert get_step_overview(trace, step_id="abc") == expected_type
    assert ask_step(trace, step_id="abc", question="hi") == expected_type
    assert verify(trace, step_id="abc") == expected_type

    assert get_step(trace, step_id=2) == expected_range
    assert get_step_overview(trace, step_id=2) == expected_range
    assert ask_step(trace, step_id=2, question="hi") == expected_range
    assert verify(trace, step_id=2) == expected_range


def test_verify_logs_progress_for_all_steps(monkeypatch):
    trace = Trace.from_string(
        "\n".join([
            """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}""",
            """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello again"}],"output":"ok","name":"demo"}""",
        ])
    )
    verify_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.verify")
    logs: list[tuple[str, tuple[object, ...]]] = []

    class FakeLogger:
        def info(self, message, *args):
            logs.append((message, args))

        def exception(self, message, *args):
            logs.append((message, args))

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
    monkeypatch.setattr(verify_module, "logger", FakeLogger())

    result = verify(trace)

    assert "2 steps verified" in result
    assert ("VERIFY all start: total_steps=%d cached=%d llm_calls=%d", (2, 0, 2)) in logs
    assert any(message == "VERIFY all progress: %d/%d complete (latest step=%d verdict=%s)" for message, _args in logs)
    assert any(message == "VERIFY all done in %.1fs: total_steps=%d wrong=%d uncertain=%d" for message, _args in logs)
