"""get_summary tool — returns (or generates) a three-sentence summary for a step."""

from ..utils.llm_backend import infer_text
from ..utils.trace import Trace, format_messages, stringify_field

SUMMARIZE_STEP_SYSTEM = (
    "You summarize a single step from an AI agent trace. "
    "Write exactly three sentences:\n"
    "1. What is the general goal of this step — what kind of input does it "
    "take and what kind of output does it produce?\n"
    "2. Characterize the specific input in this step.\n"
    "3. Characterize the specific output in this step.\n"
    "Be concise and concrete. No preamble."
)


def get_summary(trace: Trace, **params) -> str:
    step_id = params.get("step_id")
    if step_id is None:
        return "Error: 'step_id' parameter is required."
    try:
        step_id = int(step_id)
    except (TypeError, ValueError):
        return f"Error: 'step_id' must be an integer, got '{step_id}'."

    if step_id < 1 or step_id > len(trace):
        return f"Error: step_id {step_id} out of range (1–{len(trace)})."

    index = step_id - 1  # Convert to 0-based internal index
    record = trace.get(index)

    # Return existing summary if present on the record
    if record.summary:
        return f"Step {step_id} summary:\n{record.summary}"

    # Return cached summary from a prior call
    if index in trace.summary_cache:
        return f"Step {step_id} summary:\n{trace.summary_cache[index]}"

    # Generate via LLM
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    snapshot = format_messages(record.input, system_prompt=record.system_prompt)
    output = record.output if isinstance(record.output, str) else stringify_field(record.output)
    content = f"{snapshot}\n\nOutput:\n{output}"

    summary = infer_text(
        [{"role": "system", "content": SUMMARIZE_STEP_SYSTEM},
         {"role": "user", "content": content}],
        model=model,
        tier="cheap",
        max_tokens=256,
    )

    trace.summary_cache[index] = summary
    return f"Step {step_id} summary:\n{summary}"
