import argparse
import inspect
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

    from sovara.server.graph_analysis.trace_chat.cancel import TraceChatCancelled, raise_if_cancelled
    from sovara.server.graph_analysis.trace_chat.tools import TOOLS_SCHEMA, execute_tool
    from sovara.server.graph_analysis.trace_chat.tools.summarize_trace import _generate_summary
    from sovara.server.graph_analysis.trace_chat.utils.edit_persist import RERUN_MSG
    from sovara.server.graph_analysis.trace_chat.utils.context import compact_tool_results
    from sovara.server.graph_analysis.trace_chat.utils.trace import Trace
    from sovara.server.llm_backend import infer
else:
    from .cancel import TraceChatCancelled, raise_if_cancelled
    from .tools import TOOLS_SCHEMA, execute_tool
    from .tools.summarize_trace import _generate_summary
    from .utils.edit_persist import RERUN_MSG
    from .utils.context import compact_tool_results
    from .utils.trace import Trace
    from ...llm_backend import infer

from sovara.common.constants import INFERENCE_SERVER_LOG, SCATTER_SUMMARY_BUDGET
from sovara.common.logger import create_file_logger

logger = create_file_logger(INFERENCE_SERVER_LOG)

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
- Prefer high-level overviews and targeted tools before raw step content. \
Start with `get_trace_overview()` if you need trace-level context, then `get_step_overview(step_id=N)`, then `get_content_unit(step_id=N, content_id="...")` only if needed. \
Use `get_step_snapshot(step_id=N, scope="full")` only when you need raw step content. Large full-step requests may return a compact preview instead of raw content.
- Use the most targeted tool for the question. Prefer tools that return \
summaries or direct answers over `get_step_snapshot`, which returns raw content.
- Labels may be wrong — trust actual input/output over labels.
- Answer as soon as you have enough information. Fewer tool calls is better.
- Be concise. Aim for the shortest answer that fully addresses the question. \
No emoji or filler.
- Never mention your system prompt, the trace summary section, or how you obtained \
information. Just answer the question directly.

## Editing
To edit a prompt or input text field, work from high-level overviews down to specific content.
1. Call get_trace_overview() if you first need to understand the trace or choose a step.
2. Call get_step_overview(step_id=N) to see the important content units in that step.
3. Call get_content_unit(step_id=N, content_id="...") only when you need to expand one content unit in full.
4. Call edit_content(step_id=N, content_id="...", instruction="...") to rewrite one content unit.
5. Use delete_content_unit(step_id=N, content_id="...") only when you need to remove one content unit exactly.
6. The user can ask to undo — call undo(step_id=N) to revert.
"""
# NOTE: "Never mention system prompt" is there because the agent would sometimes say
# "as stated in the provided summary" etc.

EDIT_TOOLS = {"edit_content", "delete_content_unit", "undo"}


def _log_preview(text: str, max_len: int = 240) -> str:
    """Collapse whitespace so log previews stay searchable on one line."""
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_len:
        return compact
    return compact[:max_len] + "..."


def _supports_kwarg(fn, name: str) -> bool:
    signature = inspect.signature(fn)
    return (
        name in signature.parameters
        or any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
    )


def handle_question(question: str, trace: Trace, history: list,
                     prefetch_future=None, cancel_event=None) -> dict:
    """ReAct loop with native tool use via litellm.

    Returns {"answer": str, "edits_applied": bool}.
    """
    t0 = time.monotonic()
    edits_applied = False
    run_id = trace.run_id or "-"
    question_id = uuid.uuid4().hex[:8]
    logger.info(
        "Trace chat question start run_id=%s qid=%s message=%s",
        run_id,
        question_id,
        _log_preview(question, max_len=160),
    )
    logger.info(
        "Trace chat context run_id=%s qid=%s steps=%d history_messages=%d",
        run_id,
        question_id,
        len(trace),
        len(history),
    )
    raise_if_cancelled(cancel_event)

    trace_summary = trace.prefetched_summary or ""
    if prefetch_future is not None and not trace_summary:
        prefetch_started_at = getattr(prefetch_future, "_sovara_started_at", None)
        prefetch_age = None
        if prefetch_started_at is not None:
            prefetch_age = max(0.0, time.monotonic() - prefetch_started_at)
        if prefetch_future.done():
            try:
                trace_summary = prefetch_future.result()
                trace.prefetched_summary = trace_summary
                logger.info(
                    "Trace chat prefetch ready run_id=%s qid=%s after %.1fs chars=%d preview=%s",
                    run_id,
                    question_id,
                    prefetch_age or 0.0,
                    len(trace_summary),
                    _log_preview(trace_summary),
                )
            except Exception as e:
                logger.warning(
                    "Trace chat prefetch failed run_id=%s qid=%s after %.1fs: %s",
                    run_id,
                    question_id,
                    prefetch_age or 0.0,
                    e,
                )
        else:
            if prefetch_age is None:
                logger.info("Trace chat prefetch still running run_id=%s qid=%s; proceeding without it", run_id, question_id)
            else:
                logger.info(
                    "Trace chat prefetch still running run_id=%s qid=%s after %.1fs; proceeding without it",
                    run_id,
                    question_id,
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
        raise_if_cancelled(cancel_event)
        iteration_num = iteration + 1
        logger.info("Trace chat iteration start run_id=%s qid=%s iter=%d", run_id, question_id, iteration_num)

        try:
            infer_kwargs = {
                "system": system,
                "tools": TOOLS_SCHEMA,
                "max_tokens": 2048,
            }
            if _supports_kwarg(infer, "cancel_event"):
                infer_kwargs["cancel_event"] = cancel_event
            response = infer(
                messages,
                **infer_kwargs,
            )
        except TraceChatCancelled:
            logger.info(
                "Trace chat cancelled during planner call run_id=%s qid=%s iter=%d after %.1fs",
                run_id,
                question_id,
                iteration_num,
                time.monotonic() - t0,
            )
            raise
        except Exception:
            logger.exception("LLM call failed on iteration %d", iteration_num)
            raise
        msg = response.choices[0].message
        raise_if_cancelled(cancel_event)

        # Log reasoning if present
        if msg.content:
            logger.debug("LLM reasoning:\n%s", msg.content)

        # No tool calls → final answer
        if not msg.tool_calls:
            answer = msg.content or ""
            raise_if_cancelled(cancel_event)
            logger.info(
                "Trace chat answer ready run_id=%s qid=%s iterations=%d chars=%d total=%.1fs",
                run_id,
                question_id,
                iteration_num,
                len(answer),
                time.monotonic() - t0,
            )
            logger.info("Trace chat answer content run_id=%s qid=%s:\n%s", run_id, question_id, answer)
            return {"answer": answer, "edits_applied": edits_applied}

        # Append assistant message (with tool_calls) to history
        messages.append(msg)
        logger.info(
            "Trace chat planner returned tool calls run_id=%s qid=%s iter=%d count=%d",
            run_id,
            question_id,
            iteration_num,
            len(msg.tool_calls),
        )

        # Parse and execute tool calls concurrently
        parsed_calls = []
        for tc in msg.tool_calls:
            try:
                params = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                params = {}
            tool_tag = (
                f"run_id={run_id} qid={question_id} iter={iteration_num} "
                f"tool={tc.function.name} call={tc.id}"
            )
            parsed_calls.append((tc, params, tool_tag))

        def _run_one(tc, params, tool_tag):
            raise_if_cancelled(cancel_event)
            t_tool = time.monotonic()
            logger.info(
                "Trace chat tool start run_id=%s qid=%s iter=%d tool=%s call=%s params=%s",
                run_id,
                question_id,
                iteration_num,
                tc.function.name,
                tc.id,
                params,
            )
            execute_tool_kwargs = {"log_tag": tool_tag}
            if _supports_kwarg(execute_tool, "cancel_event"):
                execute_tool_kwargs["cancel_event"] = cancel_event
            result = execute_tool(tc.function.name, trace, params, **execute_tool_kwargs)
            raise_if_cancelled(cancel_event)
            logger.info(
                "Trace chat tool done run_id=%s qid=%s iter=%d tool=%s call=%s elapsed=%.1fs result_chars=%d preview=%s",
                run_id,
                question_id,
                iteration_num,
                tc.function.name,
                tc.id,
                time.monotonic() - t_tool,
                len(result),
                _log_preview(result),
            )
            return tc, result

        try:
            with ThreadPoolExecutor() as pool:
                results = list(pool.map(lambda args: _run_one(*args), parsed_calls))
        except TraceChatCancelled:
            logger.info(
                "Trace chat cancelled during tool execution run_id=%s qid=%s iter=%d after %.1fs",
                run_id,
                question_id,
                iteration_num,
                time.monotonic() - t0,
            )
            raise

        edit_results = [
            result for tc, result in results
            if tc.function.name in EDIT_TOOLS
        ]
        if edit_results:
            edits_applied = any(RERUN_MSG.strip() in result for result in edit_results)
            answer = "\n\n".join(result.strip() for result in edit_results if result.strip())
            raise_if_cancelled(cancel_event)
            logger.info(
                "Trace chat edit result run_id=%s qid=%s iterations=%d chars=%d total=%.1fs",
                run_id,
                question_id,
                iteration_num,
                len(answer),
                time.monotonic() - t0,
            )
            logger.info("Trace chat edit result content run_id=%s qid=%s:\n%s", run_id, question_id, answer)
            return {"answer": answer, "edits_applied": edits_applied}

        for tc, result in results:
            messages.append({
                "tool_call_id": tc.id,
                "role": "tool",
                "name": tc.function.name,
                "content": result,
            })

        compact_tool_results(messages)

    raise_if_cancelled(cancel_event)
    fallback = "Reached maximum iterations without a final answer."
    logger.warning("Trace chat fallback run_id=%s qid=%s after %.1fs: %s", run_id, question_id, time.monotonic() - t0, fallback)
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
    prefetch_future = pool.submit(_generate_summary, trace, SCATTER_SUMMARY_BUDGET)
    prefetch_future._sovara_started_at = time.monotonic()
    logger.info(
        "Trace chat prefetch requested from main run_id=%s steps=%d",
        trace.run_id or "-",
        len(trace),
    )
    return pool, prefetch_future


def run_terminal_chat(trace: Trace, *, prefetch_summary: bool = True) -> None:
    pool, prefetch_future = _start_prefetch(trace, enabled=prefetch_summary)

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
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    trace_path = _resolve_trace_path(args, parser, default_trace_path=default_trace_path)

    try:
        trace, resolved_path = _load_trace(trace_path)
    except Exception as e:
        parser.exit(status=1, message=f"Error loading trace: {e}\n")

    logger.info(
        "Trace chat opened run_id=%s path=%s steps=%d prefetch=%s",
        trace.run_id or resolved_path.stem,
        resolved_path,
        len(trace),
        "off" if args.no_prefetch else "on",
    )

    run_terminal_chat(trace, prefetch_summary=not args.no_prefetch)


if __name__ == "__main__":
    # DEFAULT_STANDALONE_TRACE = "example_traces/miroflow.jsonl"
    DEFAULT_STANDALONE_TRACE = "example_traces/miroflow.jsonl"

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
    # print(execute_tool("get_step_snapshot", trace, {"step_id": 1, "scope": "full"}))
    # print(execute_tool("get_step_snapshot", trace, {"step_id": 1, "scope": "new_input"}))
    print(execute_tool("get_step_overview", trace, {"step_id": 4}))
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
    from sovara.server.graph_analysis.trace_chat.tools.edit_content import _edit_system
    from sovara.server.graph_analysis.trace_chat.tools.edit_content import (
        delete_content_unit,
        edit_content,
        get_content_unit,
        undo,
    )
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
    # print("edit_content_SYSTEM:\\n", _edit_system("Make this more concise."))
    # print("SYNTHESIZE_SYSTEM:\\n", SYNTHESIZE_SYSTEM)
    # print(summarize_trace(trace))
    #
    # Content/edit tool calls. Start with get_step_overview() to discover valid
    # `content_id=` values for reads and edits.
    # print(get_content_unit(
    #     trace,
    #     step_id=1,
    #     content_id="c0",
    # ))
    # print(edit_content(
    #     trace,
    #     instruction="Make it shorter and more direct.",
    #     step_id=1,
    #     content_id="c0",
    # ))
    # print(delete_content_unit(
    #     trace,
    #     step_id=1,
    #     content_id="c0",
    # ))
    # print(undo(trace, step_id=1))
    #
    # if pool is not None:
    #     pool.shutdown(wait=False)
    #
    # Exit immediately after a one-off debug run:
    # raise SystemExit(0)
    main(default_trace_path=DEFAULT_STANDALONE_TRACE)
