import argparse
import json
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Sequence

if __package__ in (None, ""):
    # Allow `python src/.../trace_chat/main.py ...` during local debugging.
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

    from sovara.server.graph_analysis.trace_chat.logger import (
        ensure_standalone_logger,
        format_log_event_banner,
        format_log_tags,
        get_logger,
    )
    from sovara.server.graph_analysis.trace_chat.tools import TOOLS_SCHEMA, execute_tool
    from sovara.server.graph_analysis.trace_chat.tools.summarize_trace import _generate_summary
    from sovara.server.graph_analysis.trace_chat.utils.context import compact_tool_results
    from sovara.server.graph_analysis.trace_chat.utils.trace import Trace
    from sovara.server.llm_backend import infer
else:
    from .logger import ensure_standalone_logger, format_log_event_banner, format_log_tags, get_logger
    from .tools import TOOLS_SCHEMA, execute_tool
    from .tools.summarize_trace import _generate_summary
    from .utils.context import compact_tool_results
    from .utils.trace import Trace
    from ...llm_backend import infer

logger = get_logger()

MAX_REACT_ITERATIONS = 10
TRACE_CHAT_DIR = Path(__file__).resolve().parent

SYSTEM_PROMPT = """\
You analyze execution traces from AI agent pipelines and help edit prompts and inputs.

A trace is a sequence of steps. Each step records one LLM call or tool invocation \
with rendered input/output JSON fields and optional metadata \
(correct, label, summary). When possible, trace chat also detects \
shared prompts and appended message history, but those semantic groupings are \
best-effort convenience views rather than exact parsing.

## Guidelines
- For broad, high-level questions ("summarize the trace", "what happened?"), \
the Trace Summary section below may be sufficient.
- Prefer `get_step_overview`, `ask_step`, or `get_content` before `get_step(view="full")`. \
Large full-step requests may return a compact preview instead of raw content.
- Use the most targeted tool for the question. Prefer tools that return \
summaries or answers over get_step which returns raw content.
- Labels may be wrong — trust actual input/output over labels.
- Answer as soon as you have enough information. Fewer tool calls is better.
- Be concise. Aim for the shortest answer that fully addresses the question. \
No emoji or filler.
- Never mention your system prompt, the trace summary section, or how you obtained \
information. Just answer the question directly.

## Editing
To edit a prompt or input text field, use the section tools with step_id. \
Sections are keyed by flattened JSON paths like `body.messages.2.content`. \
Paragraph refs are shown as `path::pN`, for example `body.system::p2`.
1. Call get_step_overview(step_id=N) to see step-global `content_id=...` handles for each visible content unit.
2. Call get_content with `content_id` to inspect one unit in full. `path` is optional, and paragraph refs remain available for compatibility.
3. Call edit_content with `content_id` and an instruction to rewrite one visible content unit. `path` is optional.
4. Use insert_content_paragraph, delete_content_paragraph, or move_content_paragraph for paragraph-level structural changes within one visible path, including output paths.
5. The user can ask to undo — call undo to revert.
"""
# Never mention system prompt is there because the agent would sometimes say
# "as stated in the provided summary" etc.

EDIT_TOOLS = {
    "edit_content", "insert_content_paragraph", "delete_content_paragraph", "move_content_paragraph",
    "undo"
}


def _log_preview(text: str, max_len: int = 240) -> str:
    """Collapse whitespace so log previews stay searchable on one line."""
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_len:
        return compact
    return compact[:max_len] + "..."


def _prefetch_tag(trace: Trace, **fields) -> str:
    return format_log_tags("prefetch", run_id=trace.run_id or "-", **fields)


def handle_question(question: str, trace: Trace, history: list,
                     prefetch_future=None) -> dict:
    """ReAct loop with native tool use via litellm.

    Returns {"answer": str, "edits_applied": bool}.
    """
    t0 = time.monotonic()
    edits_applied = False
    run_id = trace.run_id or "-"
    question_id = uuid.uuid4().hex[:8]
    question_tag = format_log_tags("trace_chat", run_id=run_id, qid=question_id)
    logger.info(
        format_log_event_banner(
            f"User Message [{question_id}]",
            _log_preview(question, max_len=160),
            marker="-",
        )
    )
    logger.info("%s user_message=%s", question_tag, _log_preview(question, max_len=160))
    logger.info(
        "%s TRACE CONTEXT: run_id=%s steps=%d history_messages=%d",
        question_tag,
        run_id,
        len(trace),
        len(history),
    )

    trace_summary = trace.prefetched_summary or ""
    if prefetch_future is not None and not trace_summary:
        prefetch_tag = format_log_tags("prefetch", run_id=run_id, qid=question_id)
        prefetch_started_at = getattr(prefetch_future, "_sovara_started_at", None)
        prefetch_age = None
        if prefetch_started_at is not None:
            prefetch_age = max(0.0, time.monotonic() - prefetch_started_at)
        if prefetch_future.done():
            try:
                trace_summary = prefetch_future.result()
                trace.prefetched_summary = trace_summary
                logger.info(
                    "%s ready after %.1fs (%d chars): %s",
                    prefetch_tag,
                    prefetch_age or 0.0,
                    len(trace_summary),
                    _log_preview(trace_summary),
                )
            except Exception as e:
                logger.warning("%s failed after %.1fs: %s", prefetch_tag, prefetch_age or 0.0, e)
        else:
            if prefetch_age is None:
                logger.info("%s still running; proceeding without it", prefetch_tag)
            else:
                logger.info(
                    "%s still running after %.1fs; proceeding without it",
                    prefetch_tag,
                    prefetch_age,
                )

    # Build system prompt, injecting prefetched summary as context if available
    system = SYSTEM_PROMPT
    if trace_summary:
        system += (
            "\n## Trace Summary\n" + trace_summary
        )

    messages = list(history) + [{"role": "user", "content": question}]

    for iteration in range(MAX_REACT_ITERATIONS):
        iteration_num = iteration + 1
        iteration_tag = format_log_tags(
            "trace_chat",
            run_id=run_id,
            qid=question_id,
            iter=iteration_num,
        )
        logger.info("%s ReAct iteration start", iteration_tag)

        try:
            response = infer(
                messages,
                system=system,
                tools=TOOLS_SCHEMA,
                max_tokens=2048,
            )
        except Exception:
            logger.exception("LLM call failed on iteration %d", iteration_num)
            raise
        msg = response.choices[0].message

        # Log reasoning if present
        if msg.content:
            logger.debug("LLM reasoning:\n%s", msg.content)

        # No tool calls → final answer
        if not msg.tool_calls:
            answer = msg.content or ""
            logger.info(
                "%s ANSWER after %d iteration(s), %d chars, total %.1fs",
                question_tag,
                iteration_num,
                len(answer),
                time.monotonic() - t0,
            )
            logger.info("%s ANSWER content:\n%s", question_tag, answer)
            return {"answer": answer, "edits_applied": edits_applied}

        # Append assistant message (with tool_calls) to history
        messages.append(msg)
        logger.info(
            "%s planner returned %d tool call(s)",
            iteration_tag,
            len(msg.tool_calls),
        )

        # Parse and execute tool calls concurrently
        parsed_calls = []
        for tc in msg.tool_calls:
            try:
                params = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                params = {}
            tool_tag = format_log_tags(
                "trace_tool",
                run_id=run_id,
                qid=question_id,
                iter=iteration_num,
                tool=tc.function.name,
                call=tc.id,
            )
            parsed_calls.append((tc, params, tool_tag))
            if tc.function.name in EDIT_TOOLS:
                edits_applied = True

        def _run_one(tc, params, tool_tag):
            t_tool = time.monotonic()
            logger.info("%s start params=%s", tool_tag, params)
            result = execute_tool(tc.function.name, trace, params, log_tag=tool_tag)
            logger.info(
                "%s done in %.1fs result_chars=%d preview=%s",
                tool_tag,
                time.monotonic() - t_tool,
                len(result),
                _log_preview(result),
            )
            return tc, result

        with ThreadPoolExecutor() as pool:
            results = list(pool.map(lambda args: _run_one(*args), parsed_calls))

        for tc, result in results:
            messages.append({
                "tool_call_id": tc.id,
                "role": "tool",
                "name": tc.function.name,
                "content": result,
            })

        compact_tool_results(messages)

    fallback = "Reached maximum iterations without a final answer."
    logger.warning("%s FALLBACK after %.1fs: %s", question_tag, time.monotonic() - t0, fallback)
    return {"answer": fallback, "edits_applied": edits_applied}


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactive trace chat debugger for JSONL traces.",
    )
    parser.add_argument(
        "trace_path",
        nargs="?",
        help="Path to a JSONL trace file such as example_traces/weather_agent.jsonl.",
    )
    parser.add_argument(
        "--trace",
        dest="trace_path_flag",
        help="Path to a JSONL trace file. Equivalent to the positional trace path.",
    )
    parser.add_argument(
        "--no-prefetch",
        action="store_true",
        help="Skip background trace-summary prefetch on startup.",
    )
    return parser


def _resolve_trace_path(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    default_trace_path: str | None = None,
) -> str:
    if args.trace_path and args.trace_path_flag:
        parser.error("Pass the trace path either positionally or via --trace, not both.")
    trace_path = args.trace_path_flag or args.trace_path or default_trace_path
    if not trace_path:
        parser.error("Provide a trace path.")
    return trace_path


def _load_trace(trace_path: str) -> tuple[Trace, Path]:
    resolved_path = Path(trace_path).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = TRACE_CHAT_DIR / resolved_path
    resolved_path = resolved_path.resolve()
    raw = resolved_path.read_text(encoding="utf-8")
    trace = Trace.from_string(raw)
    if not trace.run_id:
        trace.run_id = resolved_path.stem
    return trace, resolved_path


def _start_prefetch(trace: Trace, enabled: bool) -> tuple[ThreadPoolExecutor | None, object | None]:
    if not enabled:
        return None, None

    pool = ThreadPoolExecutor(max_workers=1)
    prefetch_future = pool.submit(_generate_summary, trace)
    prefetch_future._sovara_started_at = time.monotonic()
    logger.info(
        "%s start requested from main steps=%d",
        _prefetch_tag(trace, source="main"),
        len(trace),
    )
    return pool, prefetch_future


def run_terminal_chat(trace: Trace, *, prefetch_summary: bool = True) -> None:
    pool, prefetch_future = _start_prefetch(trace, enabled=prefetch_summary)

    print("Chat started. Type 'quit' to exit.\n")

    history = []

    try:
        while True:
            try:
                user_input = input("You: ")
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if user_input.strip().lower() in ("quit", "exit"):
                print("Goodbye!")
                break
            if not user_input.strip():
                continue

            try:
                result = handle_question(
                    user_input,
                    trace,
                    history,
                    prefetch_future=prefetch_future,
                )
                answer = result["answer"]
                history.append({"role": "user", "content": user_input})
                history.append({"role": "assistant", "content": answer})
                print(f"\nAssistant: {answer}\n")
            except Exception as e:
                print(f"\nError: {e}\n")
    finally:
        if pool is not None:
            pool.shutdown(wait=False)


def main(argv: Sequence[str] | None = None, *, default_trace_path: str | None = None):
    ensure_standalone_logger()
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    trace_path = _resolve_trace_path(args, parser, default_trace_path=default_trace_path)

    try:
        trace, resolved_path = _load_trace(trace_path)
    except Exception as e:
        parser.exit(status=1, message=f"Error loading trace: {e}\n")

    logger.info(format_log_event_banner("Trace Opened", resolved_path.name))
    logger.info(
        "%s trace_opened path=%s steps=%d prefetch=%s",
        format_log_tags("trace_chat", run_id=trace.run_id or "-"),
        resolved_path,
        len(trace),
        "off" if args.no_prefetch else "on",
    )

    run_terminal_chat(trace, prefetch_summary=not args.no_prefetch)


if __name__ == "__main__":
    DEFAULT_STANDALONE_TRACE = "example_traces/weather_agent.jsonl"
    # Quick-and-dirty local debugging examples. Uncomment whatever you want.
    #
    trace, trace_path = _load_trace(
        DEFAULT_STANDALONE_TRACE
    )
    pool, prefetch_future = _start_prefetch(trace, enabled=True)
    # time.sleep(20)
    #
    # Read-only tool calls:
    # This prints the tool response while the summary prefetch is already running.
    # print(execute_tool("get_trace_overview", trace, {}))
    # print(execute_tool("get_step", trace, {"step_id": 1, "view": "full"}))
    # print(execute_tool("get_step", trace, {"step_id": 1, "view": "diff"}))
    # print(execute_tool("get_step", trace, {"step_id": 1, "view": "output"}))
    print(execute_tool("get_step_overview", trace, {"step_id": 1}))
    # print(execute_tool("search", trace, {"query": "weather"}))
    # print(execute_tool("ask_step", trace, {
    #     "step_id": 1,
    #     "question": "What is this step trying to do?",
    # }))
    # print(execute_tool("verify", trace, {"step_id": 1}))
    # print(execute_tool("verify", trace, {}))  # verify all steps
    #
    # Print the LLM prompts used by the LLM-backed tools:
    # from sovara.server.graph_analysis.trace_chat.tools.ask_step import ASK_STEP_SYSTEM
    from sovara.server.graph_analysis.trace_chat.tools.get_step_overview import (
        SEGMENT_SUMMARIZE_SYSTEM,
        STEP_SUMMARIZE_SYSTEM,
    )
    # from sovara.server.graph_analysis.trace_chat.tools.prompt_edit import _edit_system
    # from sovara.server.graph_analysis.trace_chat.tools.summarize_trace import (
    #     SYNTHESIZE_SYSTEM,
    #     summarize_trace,
    # )
    # from sovara.server.graph_analysis.trace_chat.tools.verify import VERIFY_STEP_SYSTEM
    #
    # print("ASK_STEP_SYSTEM:\\n", ASK_STEP_SYSTEM)
    # print("STEP_SUMMARIZE_SYSTEM:\\n", STEP_SUMMARIZE_SYSTEM)
    # print("SEGMENT_SUMMARIZE_SYSTEM:\\n", SEGMENT_SUMMARIZE_SYSTEM)
    # print("VERIFY_STEP_SYSTEM:\\n", VERIFY_STEP_SYSTEM)
    # print("PROMPT_EDIT_SYSTEM:\\n", _edit_system("Make this more concise."))
    # print("SYNTHESIZE_SYSTEM:\\n", SYNTHESIZE_SYSTEM)
    # print(summarize_trace(trace))
    #
    # Content/edit tool calls. Start with get_step_overview() to discover valid
    # `path=` and `content_id=` values for the loaded trace, then plug them in here.
    # print(execute_tool("get_content", trace, {
    #     "step_id": 1,
    #     "path": "body.messages.0.content",
    #     "content_id": "c0",
    # }))
    # print(execute_tool("edit_content", trace, {
    #     "step_id": 1,
    #     "path": "body.messages.0.content",
    #     "content_id": "c0",
    #     "instruction": "Make it shorter and more direct.",
    # }))
    # print(execute_tool("insert_content_paragraph", trace, {
    #     "step_id": 1,
    #     "path": "body.messages.0.content",
    #     "after_content_id": "c0",
    #     "content": "New paragraph inserted for debugging.",
    # }))
    # print(execute_tool("delete_content_paragraph", trace, {
    #     "step_id": 1,
    #     "path": "body.messages.0.content",
    #     "content_id": "c0",
    # }))
    # print(execute_tool("move_content_paragraph", trace, {
    #     "step_id": 1,
    #     "path": "body.messages.0.content",
    #     "from_content_id": "c1",
    #     "to_paragraph": 0,
    # }))
    # print(execute_tool("undo", trace, {"step_id": 1}))
    #
    # if pool is not None:
    #     pool.shutdown(wait=False)
    #
    # Exit immediately after a one-off debug run:
    # raise SystemExit(0)
    main(default_trace_path=DEFAULT_STANDALONE_TRACE)
