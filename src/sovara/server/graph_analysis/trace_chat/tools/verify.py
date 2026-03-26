"""verify tool — checks whether steps have correct output."""

from concurrent.futures import ThreadPoolExecutor

from ..utils.llm_backend import infer
from ..utils.trace import Trace, extract_tag, format_messages, stringify_field

VERIFY_STEP_SYSTEM = """\
You verify whether a single step's output is correct given its instructions and input.

Consider:
- What this step is supposed to do (based on its system prompt)
- Whether the output faithfully follows the instructions, regardless of whether \
the prompt itself is well-designed
- If the input appears malformed or from a failed upstream step, note this — the \
step may have produced the best possible output given bad input

Respond with exactly this format:
<summary>2-3 sentence assessment</summary>
<verdict>CORRECT or WRONG or UNCERTAIN</verdict>
"""


def _parse_verdict(raw: str) -> tuple:
    """Extract verdict and summary from the verifier response."""
    summary = extract_tag(raw, "summary")
    verdict_text = extract_tag(raw, "verdict", "UNCERTAIN").upper()
    verdict = "UNCERTAIN"
    for v in ("CORRECT", "WRONG", "UNCERTAIN"):
        if verdict_text.startswith(v):
            verdict = v
            break
    return verdict, summary


def _verify_one(trace: Trace, index: int, record, model: str):
    """Verify a single step via LLM. Returns (index, verdict, justification)."""
    if index in trace.verdict_cache:
        return (index, *trace.verdict_cache[index])

    content = format_messages(record.input, system_prompt=record.system_prompt)
    output = record.output if isinstance(record.output, str) else stringify_field(record.output)
    user_msg = f"{content}\n\n## Output\n{output}"

    response = infer(
        [{"role": "system", "content": VERIFY_STEP_SYSTEM},
         {"role": "user", "content": user_msg}],
        model=model,
        tier="cheap",
        max_tokens=256,
    )
    raw = response.choices[0].message.content or ""
    verdict, justification = _parse_verdict(raw)
    trace.verdict_cache[index] = (verdict, justification)
    return index, verdict, justification


def _resolve_cached(trace: Trace, record, idx: int):
    """Try to resolve a verdict without an LLM call. Returns (verdict, justification) or None."""
    if record.correct is not None:
        verdict = "CORRECT" if record.correct else "WRONG"
        justification = record.summary or "Pre-marked in trace data."
        trace.verdict_cache[idx] = (verdict, justification)
        return verdict, justification
    if idx in trace.verdict_cache:
        return trace.verdict_cache[idx]
    return None


def verify(trace: Trace, **params) -> str:
    step_id = params.get("step_id")
    model = params.get("model", "anthropic/claude-sonnet-4-6")

    # Single-step mode
    if step_id is not None:
        try:
            step_id = int(step_id)
        except (TypeError, ValueError):
            return f"Error: 'step_id' must be an integer, got '{step_id}'."
        if step_id < 1 or step_id > len(trace):
            return f"Error: step_id {step_id} out of range (1–{len(trace)})."

        index = step_id - 1  # Convert to 0-based internal index
        record = trace.get(index)
        cached = _resolve_cached(trace, record, index)
        if cached:
            verdict, justification = cached
        else:
            _, verdict, justification = _verify_one(trace, index, record, model)

        return f"Step {step_id}: {verdict}\n  {justification}"

    # All-steps mode
    results = []
    to_verify = []

    for record in trace.records:
        idx = record.index
        cached = _resolve_cached(trace, record, idx)
        if cached:
            results.append((idx, cached[0], cached[1]))
        else:
            to_verify.append((idx, record))

    if to_verify:
        with ThreadPoolExecutor() as pool:
            results.extend(pool.map(
                lambda args: _verify_one(trace, args[0], args[1], model),
                to_verify,
            ))

    results.sort(key=lambda x: x[0])

    lines = []
    wrong = []
    uncertain = []

    for idx, verdict, justification in results:
        marker = ""
        if verdict == "WRONG":
            marker = " ← ERROR"
            wrong.append(idx + 1)
        elif verdict == "UNCERTAIN":
            marker = " ← UNCERTAIN"
            uncertain.append(idx + 1)
        lines.append(f"Step {idx + 1}: {verdict}{marker}")
        if justification:
            lines.append(f"  {justification}")

    header_parts = [f"{len(trace)} steps verified"]
    if wrong:
        header_parts.append(f"{len(wrong)} error(s) at step(s) {wrong}")
    if uncertain:
        header_parts.append(f"{len(uncertain)} uncertain at step(s) {uncertain}")
    if not wrong and not uncertain:
        header_parts.append("all correct")

    return " | ".join(header_parts) + "\n\n" + "\n".join(lines)
