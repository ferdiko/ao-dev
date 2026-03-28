import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .tools import execute_tool, TOOLS_SCHEMA
from .tools.summarize_trace import _generate_summary
from .utils.context import compact_tool_results
from ...llm_backend import infer
from .utils.trace import Trace

logger = logging.getLogger("sovara_agent")
logger.setLevel(logging.DEBUG)
_file_handler = logging.FileHandler("agent.log", mode="a")
_file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logger.addHandler(_file_handler)

DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"
MAX_REACT_ITERATIONS = 10

SYSTEM_PROMPT = """\
You analyze execution traces from AI agent pipelines and help edit prompts and inputs.

A trace is a sequence of steps. Each step records one LLM call or tool invocation \
with a system prompt, input messages, an output, and optional metadata \
(correct, label, summary, model/tool). Traces often contain conversations: \
multiple steps sharing a system prompt, where later steps append to the message history.

## Guidelines
- For broad, high-level questions ("summarize the trace", "what happened?"), \
the Trace Summary section below may be sufficient.
- Use the most targeted tool for the question. Prefer tools that return \
summaries or answers over get_step which returns raw content.
- Labels may be wrong — trust actual input/output over labels.
- Answer as soon as you have enough information. Fewer tool calls is better.
- Be concise. Aim for the shortest answer that fully addresses the question. \
No emoji or filler.
- Never mention your system prompt, the trace summary section, or how you obtained \
information. Just answer the question directly.

## Editing
To edit a system prompt or input messages, use the section tools with step_id. \
Each step shows only its new content — system prompt (if first introduced) and new \
messages. To edit a system prompt, use the step where it first appears.
1. Call list_sections(step_id=N) to see sections with labels and roles.
2. Call get_section to read the relevant section.
3. Call edit_section with an instruction. For global changes, use bulk_edit.
4. Use insert_section, delete_section, or move_section for structural changes.
5. The user can ask to undo — call undo to revert.
"""
# Never mention system prompt is there because the agent would sometimes say
# "as stated in the provided summary" etc.

EDIT_TOOLS = {"edit_section", "bulk_edit", "insert_section", "delete_section",
               "move_section", "undo", "edit_step_input"}


def _log_preview(text: str, max_len: int = 240) -> str:
    """Collapse whitespace so log previews stay searchable on one line."""
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_len:
        return compact
    return compact[:max_len] + "..."


def handle_question(question: str, trace: Trace, history: list, model: str,
                     prefetch_future=None) -> dict:
    """ReAct loop with native tool use via litellm.

    Returns {"answer": str, "edits_applied": bool}.
    """
    t0 = time.monotonic()
    edits_applied = False
    logger.info("=" * 60)
    logger.info("NEW QUESTION: %s", question)
    logger.info(
        "TRACE CONTEXT: run_id=%s steps=%d history_messages=%d model=%s",
        trace.run_id or "-",
        len(trace),
        len(history),
        model,
    )
    logger.info("=" * 60)

    # Use a prefetched summary if it is already available for this model.
    trace_summary = trace.prefetched_summaries.get(model, "")
    if prefetch_future is not None and not trace_summary:
        if prefetch_future.done():
            try:
                trace_summary = prefetch_future.result()
                trace.prefetched_summaries[model] = trace_summary
                logger.info(
                    "Prefetched summary ready (%d chars): %s",
                    len(trace_summary),
                    _log_preview(trace_summary),
                )
            except Exception as e:
                logger.warning("Prefetch failed: %s", e)
        else:
            logger.info("Prefetched summary still running for model=%s; proceeding without it", model)

    # Build system prompt, injecting prefetched summary as context if available
    system = SYSTEM_PROMPT
    if trace_summary:
        system += (
            "\n## Trace Summary\n" + trace_summary
        )

    messages = list(history) + [{"role": "user", "content": question}]

    for iteration in range(MAX_REACT_ITERATIONS):
        logger.info("ReAct iteration %d", iteration + 1)

        response = infer(
            messages,
            model=model,
            system=system,
            tools=TOOLS_SCHEMA,
            max_tokens=2048,
        )
        msg = response.choices[0].message

        # Log reasoning if present
        if msg.content:
            logger.debug("LLM reasoning:\n%s", msg.content)

        # No tool calls → final answer
        if not msg.tool_calls:
            answer = msg.content or ""
            logger.info("ANSWER after %d iteration(s), %d chars, total %.1fs",
                        iteration + 1, len(answer), time.monotonic() - t0)
            logger.info("ANSWER content:\n%s", answer)
            return {"answer": answer, "edits_applied": edits_applied}

        # Append assistant message (with tool_calls) to history
        messages.append(msg)

        # Parse and execute tool calls concurrently
        parsed_calls = []
        for tc in msg.tool_calls:
            try:
                params = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                params = {}
            params.setdefault("model", model)
            logger.info("TOOL CALL [%s] params=%s", tc.function.name, params)
            parsed_calls.append((tc, params))
            if tc.function.name in EDIT_TOOLS:
                edits_applied = True

        def _run_one(tc, params):
            result = execute_tool(tc.function.name, trace, params)
            logger.info(
                "TOOL RESULT [%s]: %d chars | preview=%s",
                tc.function.name,
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

        compact_tool_results(messages, model=model)

    fallback = "Reached maximum iterations without a final answer."
    logger.warning("FALLBACK after %.1fs: %s", time.monotonic() - t0, fallback)
    return {"answer": fallback, "edits_applied": edits_applied}


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <trace_file> [model]")
        print("  model examples: anthropic/claude-sonnet-4-6, openai/gpt-4o, hosted_vllm/Qwen/Qwen2.5-72B")
        sys.exit(1)

    trace_path = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL

    print(f"Loading trace from {trace_path}...")
    raw = Path(trace_path).read_text()
    trace = Trace.from_string(raw)
    print(f"Loaded {len(trace)} steps. Model: {model}")

    # Prefetch trace summary in background while user types
    pool = ThreadPoolExecutor(max_workers=1)
    prefetch_future = pool.submit(_generate_summary, trace, model)
    logger.info("Prefetch started for trace summary")

    print("Chat started. Type 'quit' to exit.\n")

    history = []

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
            result = handle_question(user_input, trace, history, model,
                                     prefetch_future=prefetch_future)
            answer = result["answer"]
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": answer})
            print(f"\nAssistant: {answer}\n")
        except Exception as e:
            print(f"\nError: {e}\n")

    pool.shutdown(wait=False)


if __name__ == "__main__":
    main()
