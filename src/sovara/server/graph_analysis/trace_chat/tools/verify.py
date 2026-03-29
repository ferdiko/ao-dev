"""verify tool — checks whether steps have correct output."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ....llm_backend import infer
from ..logger import get_logger
from ..utils.step_ids import resolve_step_index
from ..utils.trace import Trace, extract_tag, render_record_markdown

logger = get_logger()

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


def _verify_one(trace: Trace, index: int, record):
    """Verify a single step via LLM. Returns (index, verdict, justification)."""
    if index in trace.verdict_cache:
        return (index, *trace.verdict_cache[index])

    step_id = index + 1
    t0 = time.monotonic()
    logger.info("VERIFY step %d start", step_id)
    user_msg = render_record_markdown(record, trace.get_diffed(index), view="full")

    try:
        response = infer(
            [{"role": "system", "content": VERIFY_STEP_SYSTEM},
             {"role": "user", "content": user_msg}],
            tier="cheap",
            max_tokens=256,
        )
        raw = response.choices[0].message.content or ""
        verdict, justification = _parse_verdict(raw)
        trace.verdict_cache[index] = (verdict, justification)
        logger.info(
            "VERIFY step %d done in %.1fs verdict=%s",
            step_id,
            time.monotonic() - t0,
            verdict,
        )
        return index, verdict, justification
    except Exception:
        logger.exception("VERIFY step %d failed after %.1fs", step_id, time.monotonic() - t0)
        raise


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


def verify(trace: Trace, step_id=None) -> str:
    t0 = time.monotonic()

    # Single-step mode
    if step_id is not None:
        index, err = resolve_step_index(trace, step_id)
        if err:
            return err
        step_id = index + 1
        record = trace.get(index)
        cached = _resolve_cached(trace, record, index)
        if cached:
            verdict, justification = cached
            logger.info("VERIFY step %d cache hit verdict=%s", step_id, verdict)
        else:
            _, verdict, justification = _verify_one(trace, index, record)

        logger.info("VERIFY single-step done in %.1fs step=%d verdict=%s",
                    time.monotonic() - t0, step_id, verdict)
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

    logger.info(
        "VERIFY all start: total_steps=%d cached=%d llm_calls=%d",
        len(trace),
        len(results),
        len(to_verify),
    )

    if to_verify:
        with ThreadPoolExecutor() as pool:
            futures = {
                pool.submit(_verify_one, trace, idx, record): idx + 1
                for idx, record in to_verify
            }
            completed = len(results)
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                completed += 1
                logger.info(
                    "VERIFY all progress: %d/%d complete (latest step=%d verdict=%s)",
                    completed,
                    len(trace),
                    result[0] + 1,
                    result[1],
                )

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

    logger.info(
        "VERIFY all done in %.1fs: total_steps=%d wrong=%d uncertain=%d",
        time.monotonic() - t0,
        len(trace),
        len(wrong),
        len(uncertain),
    )
    return " | ".join(header_parts) + "\n\n" + "\n".join(lines)
