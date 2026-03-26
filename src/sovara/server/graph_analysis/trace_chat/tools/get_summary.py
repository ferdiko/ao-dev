"""get_summary tool — returns (or generates) a three-sentence summary for a turn."""

from ..utils.llm_backend import infer_text
from ..utils.trace import Trace, format_messages, stringify_field

SUMMARIZE_TURN_SYSTEM = (
    "You summarize a single turn from an AI agent trace. "
    "Write exactly three sentences:\n"
    "1. What is the general goal of this turn — what kind of input does it "
    "take and what kind of output does it produce?\n"
    "2. Characterize the specific input in this turn.\n"
    "3. Characterize the specific output in this turn.\n"
    "Be concise and concrete. No preamble."
)


def get_summary(trace: Trace, **params) -> str:
    turn_id = params.get("turn_id")
    if turn_id is None:
        return "Error: 'turn_id' parameter is required."
    try:
        turn_id = int(turn_id)
    except (TypeError, ValueError):
        return f"Error: 'turn_id' must be an integer, got '{turn_id}'."

    if turn_id < 0 or turn_id >= len(trace):
        return f"Error: turn_id {turn_id} out of range (0–{len(trace) - 1})."

    record = trace.get(turn_id)

    # Return existing summary if present on the record
    if record.summary:
        return f"Turn {turn_id} summary:\n{record.summary}"

    # Return cached summary from a prior call
    if turn_id in trace.summary_cache:
        return f"Turn {turn_id} summary:\n{trace.summary_cache[turn_id]}"

    # Generate via LLM
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    snapshot = format_messages(record.input, system_prompt=record.system_prompt)
    output = record.output if isinstance(record.output, str) else stringify_field(record.output)
    content = f"{snapshot}\n\nOutput:\n{output}"

    summary = infer_text(
        [{"role": "system", "content": SUMMARIZE_TURN_SYSTEM},
         {"role": "user", "content": content}],
        model=model,
        tier="cheap",
        max_tokens=256,
    )

    trace.summary_cache[turn_id] = summary
    return f"Turn {turn_id} summary:\n{summary}"
