"""ask_turn tool — answers a specific question about a turn without injecting full content."""

from ..utils.llm_backend import infer_text
from ..utils.trace import Trace, format_messages, stringify_field

ASK_TURN_SYSTEM = (
    "You are answering a question about a single turn from an AI agent execution trace. "
    "The turn content (system prompt, input messages, and output) is provided below. "
    "Answer the question concisely and accurately based only on the turn content. "
    "If the answer cannot be determined from the turn content, say so."
)


def ask_turn(trace: Trace, **params) -> str:
    turn_id = params.get("turn_id")
    if turn_id is None:
        return "Error: 'turn_id' parameter is required."
    try:
        turn_id = int(turn_id)
    except (TypeError, ValueError):
        return f"Error: 'turn_id' must be an integer, got '{turn_id}'."

    if turn_id < 0 or turn_id >= len(trace):
        return f"Error: turn_id {turn_id} out of range (0–{len(trace) - 1})."

    question = params.get("question")
    if not question or not str(question).strip():
        return "Error: 'question' parameter is required."
    question = str(question).strip()

    record = trace.get(turn_id)
    model = params.get("model", "anthropic/claude-sonnet-4-6")

    snapshot = format_messages(record.input, system_prompt=record.system_prompt)
    output = record.output if isinstance(record.output, str) else stringify_field(record.output)
    content = f"{snapshot}\n\nOutput:\n{output}\n\nQuestion: {question}"

    answer = infer_text(
        [{"role": "system", "content": ASK_TURN_SYSTEM},
         {"role": "user", "content": content}],
        model=model,
        tier="cheap",
        max_tokens=512,
    )

    return f"Turn {turn_id} — Q: {question}\nA: {answer}"
