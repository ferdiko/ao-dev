"""get_summary tool — returns (or generates) a three-sentence summary for a step."""

from ....llm_backend import infer_text
from ..utils.step_ids import resolve_step_index
from ..utils.trace import Trace, render_record_markdown

SUMMARIZE_STEP_SYSTEM = (
    "You summarize a single step from an AI agent trace. "
    "Write exactly three sentences:\n"
    "1. What is the general goal of this step — what kind of input does it "
    "take and what kind of output does it produce?\n"
    "2. Characterize the specific input in this step.\n"
    "3. Characterize the specific output in this step.\n"
    "Be concise and concrete. No preamble."
)


def get_summary(trace: Trace, step_id=None) -> str:
    index, err = resolve_step_index(trace, step_id)
    if err:
        return err
    record = trace.get(index)

    # Return existing summary if present on the record
    if record.summary:
        return f"Step {step_id} summary:\n{record.summary}"

    # Return cached summary from a prior call
    if index in trace.summary_cache:
        return f"Step {step_id} summary:\n{trace.summary_cache[index]}"

    # Generate via LLM
    content = render_record_markdown(record, trace.get_diffed(index), view="full")

    summary = infer_text(
        [{"role": "system", "content": SUMMARIZE_STEP_SYSTEM},
         {"role": "user", "content": content}],
        tier="cheap",
        max_tokens=256,
    )

    trace.summary_cache[index] = summary
    return f"Step {step_id} summary:\n{summary}"
