"""ask_step tool — answers a specific question about a step without injecting full content."""

from ....llm_backend import NO_THINKING_EXTRA_BODY, infer_text
from ..utils.step_ids import resolve_step_index
from ..utils.trace import Trace, render_record_markdown

ASK_STEP_SYSTEM = (
    "You are answering a question about a single step from an AI agent execution trace. "
    "The step content (system prompt, input messages, and output) is provided below. "
    "Answer the question concisely and accurately based only on the step content. "
    "If the answer cannot be determined from the step content, say so."
)


def ask_step(trace: Trace, question, step_id=None) -> str:
    index, err = resolve_step_index(trace, step_id)
    if err:
        return err

    record = trace.get(index)

    snapshot = render_record_markdown(record, trace.get_diffed(index), view="full")
    content = f"{snapshot}\n\nQuestion: {question}"

    answer = infer_text(
        [{"role": "system", "content": ASK_STEP_SYSTEM},
         {"role": "user", "content": content}],
        tier="cheap",
        extra_body=NO_THINKING_EXTRA_BODY,
        max_tokens=512,
    )

    return f"Step {step_id} — Q: {question}\nA: {answer}"
