import importlib
import threading
from types import SimpleNamespace

import pytest

from sovara.server.graph_analysis.trace_chat.cancel import TraceChatCancelled
from sovara.server.graph_analysis.trace_chat.tools.ask_step import ask_step
from sovara.server.graph_analysis.trace_chat.tools.get_trace_overview import get_trace_overview
from sovara.server.graph_analysis.trace_chat.tools.get_step_snapshot import get_step_snapshot
from sovara.server.graph_analysis.trace_chat.tools.get_step_overview import get_step_overview
from sovara.server.graph_analysis.trace_chat.tools.edit_content import (
    delete_content_unit,
    edit_content,
    get_content_unit,
    undo,
)
from sovara.server.graph_analysis.trace_chat.utils.edit_persist import PersistOutcome
from sovara.server.graph_analysis.trace_chat.utils.editable_content import EditableContentState, PathContent
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
    step = get_step_snapshot(trace, step_id=1)

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

    result = get_step_snapshot(trace, step_id=1, scope="full")

    assert "Paragraph 1:" not in result
    assert "Summary:" not in result
    assert "Line 1\n\nLine 2\n\n## Heading\n\nBody text" in result
    assert "Alpha\n\nBeta" in result
    assert "Result line 1\n\nResult line 2" in result


def test_get_step_new_input_preserve_raw_text():
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {"messages": [{"role": "user", "content": "First line\n\nSecond line"}]},
            {"output": "Output line 1\n\nOutput line 2"},
            index=0,
            name="demo",
        )
    ])

    new_input_result = get_step_snapshot(trace, step_id=1, scope="new_input")

    assert "Paragraph 1:" not in new_input_result
    assert "Summary:" not in new_input_result
    assert "First line\n\nSecond line" in new_input_result
    assert "Output line 1\n\nOutput line 2" in new_input_result


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


def test_editable_content_assigns_content_ids_for_flattened_paths():
    raw = """{"system_prompt":"You are concise.","input":[{"role":"user","content":"First paragraph."}],"output":"ok","name":"demo"}"""
    trace = Trace.from_string(raw)

    single = get_content_unit(trace, step_id=1, content_id="c2")

    assert "[content_id=c2]" in single
    assert "`messages.0.content`" in single
    assert single.endswith("First paragraph.")


def test_editable_content_handles_graph_style_flattened_input_paths():
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

    updated = get_content_unit(trace, step_id=1, content_id="c2")

    assert "[content_id=c2]" in updated
    assert "`body.messages.0.content`" in updated
    assert updated.endswith("First paragraph.")


def test_step_edit_invalidates_cached_analysis():
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )
    _seed_stale_analysis(trace, [0])

    edit_content_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.edit_content"
    )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        edit_content_module,
        "infer_text",
        lambda *args, **kwargs: "Hello\n\nSecond paragraph.",
    )
    try:
        edit_content(trace, step_id=1, content_id="c2", instruction="Add another paragraph.")
    finally:
        monkeypatch.undo()

    assert trace.records[0].summary is None
    assert trace.records[0].correct is None
    assert trace.diffed[0].summary is None
    assert trace.diffed[0].correct is None
    assert trace.summary_cache == {}
    assert trace.step_overview_cache == {}
    assert trace.step_semantic_summary_cache == {}
    assert trace.verdict_cache == {}
    assert trace.prefetched_summary == ""


def test_shared_edit_content_invalidates_all_steps_using_that_prompt():
    trace = Trace.from_string(
        "\n".join([
            """{"system_prompt":"Shared prompt.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}""",
            """{"system_prompt":"Shared prompt.","input":[{"role":"user","content":"Hello again"}],"output":"ok","name":"demo"}""",
        ])
    )
    _seed_stale_analysis(trace, [0, 1])

    edit_content_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.edit_content"
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        edit_content_module,
        "infer_text",
        lambda *args, **kwargs: "Shared prompt.\n\nAdded paragraph.",
    )
    try:
        edit_content(trace, step_id=1, content_id="c0", instruction="Add another paragraph.")
    finally:
        monkeypatch.undo()

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

    edit_content_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.edit_content"
    )
    monkeypatch.setattr(
        edit_content_module,
        "infer_text",
        lambda *args, **kwargs: "Hello\n\nSecond paragraph.",
    )
    edit_content(trace, step_id=1, content_id="c2", instruction="Add another paragraph.")

    summary = get_step_overview(trace, step_id=1)

    assert "cached step overview 0" not in summary
    assert "## Three-Sentence Summary" in summary
    assert "## Input Content" in summary
    assert "`messages.0.content`" in summary
    assert "content_id=c0" in summary
    assert verify(trace, step_id=1) == "Step 1: I think this is correct. fresh verdict"


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
    get_step_snapshot_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.get_step_snapshot"
    )
    monkeypatch.setattr(get_step_snapshot_module, "MAX_FULL_STEP_CHARS", 80)

    result = get_step_snapshot(trace, step_id=1, scope="full")
    record = trace.get(0)

    assert "Step 1 is too long to load inline in requested `full` scope" in result
    assert (
        f"({blocks_char_count(record.input_blocks)} input chars, "
        f"{blocks_char_count(record.output_blocks)} output chars)."
    ) in result
    assert "Showing `get_step_overview` instead:" in result
    assert "`get_content_unit(step_id=1, content_id=\"c0\")`" in result
    assert "`get_step_snapshot(step_id=1, scope=\"new_input\")`" in result
    assert "very long content " * 80 not in result
    assert "`body.messages.0.content`" in result


def test_get_step_new_input_returns_compact_preview_for_large_steps(monkeypatch):
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
    get_step_snapshot_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.get_step_snapshot"
    )
    monkeypatch.setattr(get_step_snapshot_module, "MAX_FULL_STEP_CHARS", 80)

    result = get_step_snapshot(trace, step_id=1, scope="new_input")
    record = trace.get(0)

    assert "Step 1 is too long to load inline in requested `new_input` scope" in result
    assert (
        f"({blocks_char_count(record.input_blocks)} input chars, "
        f"{blocks_char_count(record.output_blocks)} output chars)."
    ) in result
    assert "Showing `get_step_overview` instead:" in result
    assert "`get_content_unit(step_id=1, content_id=\"c0\")`" in result
    assert "`get_step_snapshot(step_id=1, scope=\"new_input\")`" in result
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


def test_get_step_overview_segment_summaries_use_timeout_fallback(monkeypatch):
    trace = Trace(raw="", records=[], run_id="run-1")
    step_overview_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.get_step_overview"
    )
    content_items_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.utils.content_items"
    )
    scatter_calls: dict[str, object] = {}

    items = [
        content_items_module.StepContentItem(
            content_id="c0",
            branch="input",
            path="messages.0.content",
            display_path="messages.0.content",
            codec="plain_text",
            text="alpha beta gamma delta epsilon zeta",
            summarized=True,
        ),
        content_items_module.StepContentItem(
            content_id="c1",
            branch="input",
            path="messages.1.content",
            display_path="messages.1.content",
            codec="plain_text",
            text="one two three four five six",
            summarized=True,
        ),
    ]

    def fake_scatter_execute(items, run_one, **kwargs):
        scatter_calls["items"] = items
        scatter_calls["max_workers"] = kwargs["max_workers"]
        kwargs["on_timeout"](list(items))
        return [None] * len(items)

    monkeypatch.setattr(step_overview_module, "scatter_execute", fake_scatter_execute)

    result = step_overview_module._summarize_content_items(trace, step_id=1, items=items)

    assert result == {
        "c0": "alpha beta gamma delta epsilon",
        "c1": "one two three four five",
    }
    assert len(scatter_calls["items"]) == 2
    assert scatter_calls["max_workers"] == 2


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
        user_content = messages[1]["content"]
        if "Second paragraph is also long enough" in user_content:
            return "i0\tSecond paragraph summary"
        if "First paragraph is intentionally long enough" in user_content:
            return "i0\tFirst paragraph summary"
        return "i0\tUser role label"

    monkeypatch.setattr(step_overview_module, "infer_text", fake_infer_text)

    summary = get_step_overview(trace, step_id=1)
    expanded = get_content_unit(trace, step_id=1, content_id="c2")

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
    edit_content_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.edit_content"
    )

    monkeypatch.setattr(edit_content_module, "infer_text", lambda *args, **kwargs: "Edited second paragraph.")

    result = edit_content(
        trace,
        step_id=1,
        content_id="c2",
        instruction="Rewrite this paragraph.",
    )
    updated = get_content_unit(trace, step_id=1, content_id="c2")

    assert "content_id=c2" in result
    assert updated.endswith("Edited second paragraph.")


def test_edit_content_does_not_write_back_after_cancellation(monkeypatch):
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
    cancel_event = threading.Event()
    write_calls: list[tuple[object, ...]] = []
    edit_content_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.edit_content"
    )

    def fake_infer_text(*args, **kwargs):
        cancel_event.set()
        return "Edited second paragraph."

    monkeypatch.setattr(edit_content_module, "infer_text", fake_infer_text)
    monkeypatch.setattr(
        edit_content_module,
        "_write_back",
        lambda *args, **kwargs: write_calls.append(args) or PersistOutcome(ok=True),
    )

    with pytest.raises(TraceChatCancelled):
        edit_content(
            trace,
            step_id=1,
            content_id="c2",
            instruction="Rewrite this paragraph.",
            cancel_event=cancel_event,
        )

    assert write_calls == []


def test_edit_content_persists_against_the_actual_run_id(monkeypatch):
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {
                "body": {
                    "messages": [
                        {
                            "role": "user",
                            "content": "Question about a Swiss company.",
                        }
                    ]
                }
            },
            {"output": "ok"},
            index=0,
            name="demo",
            node_uuid="node-1",
        )
    ])
    trace.run_id = "actual-run-id"
    edit_content_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.edit_content"
    )
    persisted_run_ids: list[str] = []

    monkeypatch.setattr(
        edit_content_module,
        "infer_text",
        lambda *args, **kwargs: "Question about recent OpenAI news.",
    )
    monkeypatch.setattr(
        edit_content_module,
        "write_input_content_edit",
        lambda trace, step_index, state: (
            persisted_run_ids.append(trace.run_id),
            PersistOutcome(ok=True, message="\n\nEdit applied and saved."),
        )[1],
    )

    result = edit_content(
        trace,
        step_id=1,
        content_id="c0",
        instruction="Rewrite the question.",
    )

    assert persisted_run_ids == ["actual-run-id"]
    assert "Edited content_id=c0" in result


def test_write_input_content_edit_falls_back_to_graph_when_llm_call_is_missing(monkeypatch):
    edit_persist_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.utils.edit_persist"
    )
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {"body": {"messages": [{"role": "user", "content": "Original question."}]}},
            {"output": "ok"},
            index=0,
            name="demo",
            node_uuid="node-1",
        )
    ])
    trace.run_id = "run-1"
    state = EditableContentState(paths=[
        PathContent(
            path="body.messages.0.content",
            paragraphs=["Edited question."],
            codec="plain_text",
            branch="input",
            role="user",
        )
    ])
    persisted_updates: list[tuple[str, str, str, object]] = []

    monkeypatch.setattr(edit_persist_module, "_read_to_show", lambda run_id, node_uuid: None)
    monkeypatch.setattr(
        edit_persist_module,
        "_read_graph_to_show",
        lambda run_id, node_uuid, branch: {"body": {"messages": [{"role": "user", "content": "Original question."}]}},
    )
    monkeypatch.setattr(
        edit_persist_module,
        "_post_update_node_json",
        lambda run_id, node_uuid, branch, payload: (
            persisted_updates.append((run_id, node_uuid, branch, payload)),
            True,
        )[1],
    )

    result = edit_persist_module.write_input_content_edit(trace, 0, state)

    assert result == PersistOutcome(
        ok=True,
        message=edit_persist_module.DISPLAY_ONLY_MSG,
    )
    assert persisted_updates == [
        (
            "run-1",
            "node-1",
            "input",
            {"body": {"messages": [{"role": "user", "content": "Edited question."}]}},
        )
    ]


def test_write_output_content_edit_falls_back_to_graph_when_llm_output_to_show_is_missing(monkeypatch):
    edit_persist_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.utils.edit_persist"
    )
    trace = Trace.from_records([
        build_trace_record_from_to_show(
            {"body": {"messages": [{"role": "user", "content": "Original question."}]}},
            {"content.content": [{"text": "Original answer."}]},
            index=0,
            name="demo",
            node_uuid="node-1",
        )
    ])
    trace.run_id = "run-1"
    state = EditableContentState(paths=[
        PathContent(
            path="content.content.0.text",
            paragraphs=["Edited answer."],
            codec="plain_text",
            branch="output",
        )
    ])
    persisted_updates: list[tuple[str, str, str, object]] = []

    monkeypatch.setattr(edit_persist_module, "_read_output_to_show", lambda run_id, node_uuid: None)
    monkeypatch.setattr(
        edit_persist_module,
        "_read_graph_to_show",
        lambda run_id, node_uuid, branch: {"content.content": [{"text": "Original answer."}]},
    )
    monkeypatch.setattr(
        edit_persist_module,
        "_post_update_node_json",
        lambda run_id, node_uuid, branch, payload: (
            persisted_updates.append((run_id, node_uuid, branch, payload)),
            True,
        )[1],
    )

    result = edit_persist_module.write_output_content_edit(trace, 0, state)

    assert result == PersistOutcome(
        ok=True,
        message=edit_persist_module.DISPLAY_ONLY_MSG,
    )
    assert persisted_updates == [
        (
            "run-1",
            "node-1",
            "output",
            {"content.content": [{"text": "Edited answer."}]},
        )
    ]


def test_delete_content_unit_accepts_content_id():
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

    deleted = delete_content_unit(
        trace,
        step_id=1,
        content_id="c2",
    )
    updated = get_content_unit(trace, step_id=1, content_id="c2")

    assert "Deleted" in deleted
    assert updated.endswith("Third paragraph.")


def test_tool_registry_exposes_get_step_overview():
    tools_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools")

    assert "get_step_overview" in tools_module.TOOL_FUNCTIONS
    assert "get_content_unit" in tools_module.TOOL_FUNCTIONS
    assert "get_step_snapshot" in tools_module.TOOL_FUNCTIONS
    assert "delete_content_unit" in tools_module.TOOL_FUNCTIONS
    assert any(tool["function"]["name"] == "get_step_overview" for tool in tools_module.TOOLS_SCHEMA)
    assert any(tool["function"]["name"] == "get_content_unit" for tool in tools_module.TOOLS_SCHEMA)
    assert any(tool["function"]["name"] == "get_step_snapshot" for tool in tools_module.TOOLS_SCHEMA)


def test_edit_tool_schemas_require_step_id():
    tools_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools")
    schemas = {
        tool["function"]["name"]: tool["function"]["parameters"]["required"]
        for tool in tools_module.TOOLS_SCHEMA
    }

    assert schemas["get_content_unit"] == ["step_id", "content_id"]
    assert schemas["edit_content"] == ["step_id", "content_id", "instruction"]
    assert schemas["delete_content_unit"] == ["step_id", "content_id"]
    assert schemas["undo"] == ["step_id"]


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

    assert result.startswith("Trace: 2 steps, 1 conversation(s)\n")
    assert result.endswith("Trace summary")
    assert any(system == summarize_module.STEP_SUMMARIZE_SYSTEM for system, _user in calls)
    assert any(
        system == summarize_module.SYNTHESIZE_SYSTEM and "Sentence one. Sentence two. Sentence three." in user
        for system, user in calls
    )


def test_summarize_trace_synthesis_uses_cheap_no_thinking(monkeypatch):
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )
    summarize_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.summarize_trace")
    step_overview_module = importlib.import_module(
        "sovara.server.graph_analysis.trace_chat.tools.get_step_overview"
    )
    synth_kwargs: dict[str, object] = {}

    def fake_infer_text(messages, **kwargs):
        if messages[0]["content"] == summarize_module.SYNTHESIZE_SYSTEM:
            synth_kwargs.update(kwargs)
            return "Trace summary"
        return "Sentence one. Sentence two. Sentence three."

    monkeypatch.setattr(summarize_module, "infer_text", fake_infer_text)
    monkeypatch.setattr(step_overview_module, "infer_text", fake_infer_text)

    result = summarize_module.summarize_trace(trace)

    assert result.startswith("Trace: 1 steps, 1 conversation(s)\n")
    assert result.endswith("Trace summary")
    assert synth_kwargs["tier"] == "cheap"
    assert synth_kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert synth_kwargs["max_tokens"] == summarize_module._SYNTHESIS_MAX_TOKENS


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

    monkeypatch.setattr(
        summarize_module,
        "get_trace_overview",
        lambda trace: "Trace: 2 steps, 1 conversation(s)\n\noverview",
    )
    monkeypatch.setattr(
        summarize_module,
        "get_or_compute_step_semantic_summary",
        lambda trace, step_id: f"semantic summary {step_id}",
    )
    monkeypatch.setattr(summarize_module, "infer_text", lambda messages, **kwargs: "Trace summary")
    monkeypatch.setattr(summarize_module, "logger", FakeLogger())

    result = summarize_module._generate_summary(trace)

    assert result == "Trace: 2 steps, 1 conversation(s)\nTrace summary"
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


def test_generate_summary_uses_fallback_for_unfinished_step_summaries(monkeypatch):
    trace = Trace.from_string(
        "\n".join([
            """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}""",
            """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello again"}],"output":"done","name":"demo"}""",
        ])
    )
    trace.run_id = "run-1"
    summarize_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.summarize_trace")
    synth_inputs: list[str] = []
    scatter_calls: dict[str, object] = {}

    class FakeLogger:
        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

    def fake_infer_text(messages, **kwargs):
        synth_inputs.append(messages[1]["content"])
        return "Trace summary"

    def fake_scatter_execute(items, run_one, **kwargs):
        scatter_calls["items"] = list(items)
        scatter_calls["max_workers"] = kwargs["max_workers"]
        kwargs["on_timeout"](list(items))
        return [None] * len(items)

    monkeypatch.setattr(
        summarize_module,
        "get_trace_overview",
        lambda trace: "Trace: 2 steps, 1 conversation(s)\n\noverview",
    )
    monkeypatch.setattr(summarize_module, "scatter_execute", fake_scatter_execute)
    monkeypatch.setattr(summarize_module, "infer_text", fake_infer_text)
    monkeypatch.setattr(summarize_module, "logger", FakeLogger())

    result = summarize_module._generate_summary(trace)

    assert result == "Trace: 2 steps, 1 conversation(s)\nTrace summary"
    assert synth_inputs
    assert "Step 1 summary:\nThis `demo` step takes" in synth_inputs[0]
    assert "Step 2 summary:\nThis `demo` step takes" in synth_inputs[0]
    assert scatter_calls["items"] == [1, 2]
    assert scatter_calls["max_workers"] == 2


def test_generate_summary_does_not_duplicate_structural_header(monkeypatch):
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )
    summarize_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.summarize_trace")

    monkeypatch.setattr(
        summarize_module,
        "get_trace_overview",
        lambda trace: "Trace: 1 steps, 1 conversation(s)\n\nStep 1 | demo | 1 input chars (diff) | 2 output chars",
    )
    monkeypatch.setattr(
        summarize_module,
        "get_or_compute_step_semantic_summary",
        lambda trace, step_id: "Sentence one. Sentence two. Sentence three.",
    )
    monkeypatch.setattr(
        summarize_module,
        "infer_text",
        lambda messages, **kwargs: "Trace: 1 steps, 1 conversation(s)\nTrace summary",
    )

    result = summarize_module._generate_summary(trace)

    assert result == "Trace: 1 steps, 1 conversation(s)\nTrace summary"


def test_read_tools_share_step_id_validation_messages():
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )

    expected_type = "Error: 'step_id' must be an integer, got 'abc'."
    expected_range = "Error: step_id 2 out of range (1–1)."

    assert get_step_snapshot(trace, step_id="abc") == expected_type
    assert get_step_overview(trace, step_id="abc") == expected_type
    assert ask_step(trace, step_id="abc", question="hi") == expected_type
    assert verify(trace, step_id="abc") == expected_type

    assert get_step_snapshot(trace, step_id=2) == expected_range
    assert get_step_overview(trace, step_id=2) == expected_range
    assert ask_step(trace, step_id=2, question="hi") == expected_range
    assert verify(trace, step_id=2) == expected_range


def test_edit_tools_share_step_id_validation_messages():
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )

    expected_missing = "Error: 'step_id' parameter is required."
    expected_type = "Error: 'step_id' must be an integer, got 'abc'."
    expected_range = "Error: step_id 2 out of range (1–1)."

    assert get_content_unit(trace, content_id="c0") == expected_missing
    assert edit_content(trace, instruction="rewrite", content_id="c0") == expected_missing
    assert delete_content_unit(trace, content_id="c0") == expected_missing
    assert undo(trace) == expected_missing

    assert get_content_unit(trace, step_id="abc", content_id="c0") == expected_type
    assert edit_content(trace, step_id="abc", instruction="rewrite", content_id="c0") == expected_type
    assert delete_content_unit(trace, step_id="abc", content_id="c0") == expected_type
    assert undo(trace, step_id="abc") == expected_type

    assert get_content_unit(trace, step_id=2, content_id="c0") == expected_range
    assert edit_content(trace, step_id=2, instruction="rewrite", content_id="c0") == expected_range
    assert delete_content_unit(trace, step_id=2, content_id="c0") == expected_range
    assert undo(trace, step_id=2) == expected_range


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
    assert any(
        message == "VERIFY all done in %.1fs: total_steps=%d wrong=%d uncertain=%d unknown=%d"
        for message, _args in logs
    )


def test_verify_all_uses_timeout_fallback(monkeypatch):
    trace = Trace.from_string(
        "\n".join([
            """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}""",
            """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello again"}],"output":"ok","name":"demo"}""",
        ])
    )
    verify_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.verify")
    scatter_calls: dict[str, object] = {}

    def fake_scatter_execute(items, run_one, **kwargs):
        scatter_calls["items"] = list(items)
        kwargs["on_timeout"](list(items))
        return [None] * len(items)

    monkeypatch.setattr(verify_module, "scatter_execute", fake_scatter_execute)

    result = verify(trace)

    assert result.startswith("2 steps verified | 2 unknown at step(s) [1, 2]")
    assert (
        "Step 1: I didn't evaluate if this step is correct because verification did not complete before fallback was applied."
        in result
    )
    assert (
        "Step 2: I didn't evaluate if this step is correct because verification did not complete before fallback was applied."
        in result
    )
    assert trace.verdict_cache == {}
    assert scatter_calls["items"] == [0, 1]


def test_verify_returns_error_for_empty_or_malformed_verifier_output(monkeypatch):
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )
    verify_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.verify")

    monkeypatch.setattr(
        verify_module,
        "infer",
        lambda *args, **kwargs: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content="", reasoning_content="thinking"),
                )
            ]
        ),
    )

    result = verify(trace, step_id=1)

    assert result == "Step 1: I didn't evaluate if this step is correct because verifier returned empty content."
    assert trace.verdict_cache == {}


def test_verify_all_distinguishes_wrong_from_unknown(monkeypatch):
    trace = Trace.from_string(
        "\n".join([
            """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}""",
            """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hi"}],"output":"bad","correct":false,"summary":"Recorded wrong output.","name":"demo"}""",
        ])
    )
    verify_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.verify")

    monkeypatch.setattr(
        verify_module,
        "infer",
        lambda *args, **kwargs: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content="", reasoning_content="thinking"),
                )
            ]
        ),
    )

    result = verify(trace)

    assert result.startswith(
        "2 steps verified | 1 wrong at step(s) [2] | 1 unknown at step(s) [1]"
    )
    assert "Step 1: I didn't evaluate if this step is correct because verifier returned empty content." in result
    assert "Step 2: I think this is wrong. Recorded wrong output." in result
    assert trace.verdict_cache == {1: ("WRONG", "Recorded wrong output.")}


def test_verify_formats_uncertain_verdict_in_plain_language(monkeypatch):
    trace = Trace.from_string(
        """{"system_prompt":"You are concise.","input":[{"role":"user","content":"Hello"}],"output":"ok","name":"demo"}"""
    )
    verify_module = importlib.import_module("sovara.server.graph_analysis.trace_chat.tools.verify")

    monkeypatch.setattr(
        verify_module,
        "infer",
        lambda *args, **kwargs: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="<summary>Need more context to be sure.</summary><verdict>UNCERTAIN</verdict>"
                    )
                )
            ]
        ),
    )

    result = verify(trace, step_id=1)

    assert result == "Step 1: I'm uncertain if this is correct. Need more context to be sure."
