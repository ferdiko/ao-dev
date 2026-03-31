"""verify tool — checks whether steps have correct output."""

import time

from sovara.common.constants import TRACE_CHAT_SCATTER_BUDGET_SECONDS

from ....llm_backend import NO_THINKING_EXTRA_BODY, infer, scatter_execute
from ..logger import get_logger
from ..utils.step_ids import resolve_step_index
from ..utils.trace import Trace, extract_tag, render_record_markdown

logger = get_logger()
_VERIFY_STEP_MAX_TOKENS = 512
_VERDICT_PHRASES = {
    "CORRECT": "I think this is correct.",
    "WRONG": "I think this is wrong.",
    "UNCERTAIN": "I'm uncertain if this is correct.",
    "UNKNOWN": "I didn't evaluate if this step is correct.",
}

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
Do not output anything else.
"""


def _parse_verdict(raw: str) -> tuple:
    """Extract verdict and summary from the verifier response."""
    raw = (raw or "").strip()
    if not raw:
        return "UNKNOWN", "Verifier returned empty content."

    summary = extract_tag(raw, "summary")
    verdict_text = extract_tag(raw, "verdict").upper()
    if not verdict_text:
        return "UNKNOWN", "Verifier response was missing a <verdict> tag."

    verdict = None
    for v in ("CORRECT", "WRONG", "UNCERTAIN"):
        if verdict_text.startswith(v):
            verdict = v
            break
    if verdict is None:
        return "UNKNOWN", f"Verifier returned an unrecognized verdict: {verdict_text!r}."
    if not summary:
        return "UNKNOWN", "Verifier response was missing a non-empty <summary> tag."
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
            extra_body=NO_THINKING_EXTRA_BODY,
            max_tokens=_VERIFY_STEP_MAX_TOKENS,
        )
        choice = response.choices[0]
        message = choice.message
        raw = message.content or ""
        verdict, justification = _parse_verdict(raw)
        if verdict != "UNKNOWN":
            trace.verdict_cache[index] = (verdict, justification)
        else:
            logger.warning(
                "VERIFY step %d malformed verifier response finish_reason=%r reasoning_chars=%d raw=%r",
                step_id,
                getattr(choice, "finish_reason", None),
                len(getattr(message, "reasoning_content", None) or ""),
                raw[:400],
            )
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


def _format_verification_line(step_id: int, verdict: str, justification: str) -> str:
    phrase = _VERDICT_PHRASES.get(verdict, _VERDICT_PHRASES["UNKNOWN"])
    if not justification:
        return f"Step {step_id}: {phrase}"
    if verdict == "UNKNOWN":
        return f"Step {step_id}: {phrase.rstrip('.')} because {justification[:1].lower()}{justification[1:]}"
    return f"Step {step_id}: {phrase} {justification}"


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
        return _format_verification_line(step_id, verdict, justification)

    # All-steps mode
    results = []
    to_verify = []

    for record in trace.records:
        idx = record.index
        cached = _resolve_cached(trace, record, idx)
        if cached:
            results.append((idx, cached[0], cached[1]))
        else:
            to_verify.append(idx)

    logger.info(
        "VERIFY all start: total_steps=%d cached=%d llm_calls=%d",
        len(trace),
        len(results),
        len(to_verify),
    )

    if to_verify:
        completed = len(results)
        def _run_one(idx: int):
            return _verify_one(trace, idx, trace.get(idx))

        def _on_verify_result(_idx: int, result) -> None:
            nonlocal completed
            completed += 1
            logger.info(
                "VERIFY all progress: %d/%d complete (latest step=%d verdict=%s)",
                completed,
                len(trace),
                result[0] + 1,
                result[1],
            )

        def _on_verify_exception(idx: int, _exc: Exception) -> None:
            logger.exception(
                "VERIFY all future failed; using UNKNOWN fallback for step %d",
                idx + 1,
            )

        def _on_verify_timeout(timeout_indices: list[int]) -> None:
            timeout_steps = sorted(idx + 1 for idx in timeout_indices)
            logger.warning(
                "VERIFY all deadline reached after %.1fs fallback=%d steps=%s",
                TRACE_CHAT_SCATTER_BUDGET_SECONDS,
                len(timeout_steps),
                timeout_steps,
            )

        verified = scatter_execute(
            to_verify,
            _run_one,
            budget_seconds=TRACE_CHAT_SCATTER_BUDGET_SECONDS,
            on_result=_on_verify_result,
            on_exception=_on_verify_exception,
            on_timeout=_on_verify_timeout,
        )
        for idx, result in zip(to_verify, verified):
            results.append(
                result
                if result is not None
                else (
                    idx,
                    "UNKNOWN",
                    "Verification did not complete before fallback was applied.",
                )
            )

    results.sort(key=lambda x: x[0])

    lines = []
    wrong = []
    uncertain = []
    unknown = []

    for idx, verdict, justification in results:
        if verdict == "WRONG":
            wrong.append(idx + 1)
        elif verdict == "UNCERTAIN":
            uncertain.append(idx + 1)
        elif verdict == "UNKNOWN":
            unknown.append(idx + 1)
        lines.append(_format_verification_line(idx + 1, verdict, justification))

    header_parts = [f"{len(trace)} steps verified"]
    if wrong:
        header_parts.append(f"{len(wrong)} wrong at step(s) {wrong}")
    if uncertain:
        header_parts.append(f"{len(uncertain)} uncertain at step(s) {uncertain}")
    if unknown:
        header_parts.append(f"{len(unknown)} unknown at step(s) {unknown}")
    if not wrong and not uncertain and not unknown:
        header_parts.append("all correct")

    logger.info(
        "VERIFY all done in %.1fs: total_steps=%d wrong=%d uncertain=%d unknown=%d",
        time.monotonic() - t0,
        len(trace),
        len(wrong),
        len(uncertain),
        len(unknown),
    )
    return " | ".join(header_parts) + "\n\n" + "\n".join(lines)
