"""ask_step tool — answers a specific question about a step without injecting full content."""

from ..utils.llm_backend import infer_text
from ..utils.trace import Trace, format_messages, stringify_field

ASK_STEP_SYSTEM = (
    "You are answering a question about a single step from an AI agent execution trace. "
    "The step content (system prompt, input messages, and output) is provided below. "
    "Answer the question concisely and accurately based only on the step content. "
    "If the answer cannot be determined from the step content, say so."
)


def ask_step(trace: Trace, **params) -> str:
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

    question = params.get("question")
    if not question or not str(question).strip():
        return "Error: 'question' parameter is required."
    question = str(question).strip()

    record = trace.get(index)
    model = params.get("model", "anthropic/claude-sonnet-4-6")

    snapshot = format_messages(record.input, system_prompt=record.system_prompt)
    output = record.output if isinstance(record.output, str) else stringify_field(record.output)
    content = f"{snapshot}\n\nOutput:\n{output}\n\nQuestion: {question}"

    answer = infer_text(
        [{"role": "system", "content": ASK_STEP_SYSTEM},
         {"role": "user", "content": content}],
        model=model,
        tier="cheap",
        max_tokens=512,
    )

    return f"Step {step_id} — Q: {question}\nA: {answer}"
