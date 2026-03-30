"""summarize_trace tool — one-shot full trace summary, avoiding extra ReAct rounds."""

import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from ....llm_backend import NO_THINKING_EXTRA_BODY, infer_text
from ..logger import format_log_tags, get_logger
from ..utils.trace import Trace, blocks_char_count, stringify_field
from .get_step_overview import (
    STEP_SUMMARIZE_SYSTEM,
    get_cached_step_semantic_summary,
    get_or_compute_step_semantic_summary,
)
from .get_trace_overview import get_trace_overview

_STEP_SUMMARY_BUDGET_SECONDS = 5.0
_STEP_SUMMARY_MAX_WORKERS = 8
_STEP_SUMMARY_PREVIEW_CHARS = 140
_SYNTHESIS_MAX_TOKENS = 1024

SYNTHESIZE_SYSTEM = (
    "You summarize AI agent execution traces. You receive a structural overview "
    "and per-step summaries. Write a short summary that covers:\n"
    "1. The task/goal and key inputs.\n"
    "2. A structural walkthrough grouping steps into phases (e.g. 'Steps 1-3: "
    "orchestrator delegated search. Steps 4-6: worker queried Google News, found "
    "7 articles about X and Y.'). Include specific results, decisions, and errors "
    "— not just which agent ran.\n"
    "3. The outcome and why it succeeded or failed.\n"
    "One line per phase. No headers, emoji, or filler."
)

logger = get_logger()


def _prefetch_tag(trace: Trace, **fields) -> str:
    return format_log_tags("prefetch", run_id=trace.run_id or "-", **fields)


def _summarize_step_semantically(trace: Trace, step_id: int) -> str:
    step_tag = _prefetch_tag(trace, phase="step", step=step_id)
    t0 = time.monotonic()
    semantic_summary = get_or_compute_step_semantic_summary(trace, step_id)
    logger.info(
        "%s semantic summary ready in %.1fs chars=%d",
        step_tag,
        time.monotonic() - t0,
        len(semantic_summary),
    )
    return f"Step {step_id} summary:\n{semantic_summary}"


def _compact_preview(text: str, *, max_len: int = _STEP_SUMMARY_PREVIEW_CHARS) -> str:
    compact = " ".join(str(text).split()).strip()
    if not compact:
        return "(empty)"
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


def _preview_blocks(blocks) -> str:
    for block in blocks:
        raw_text = block.text if block.kind == "text" else stringify_field(block.raw_value)
        preview = _compact_preview(raw_text)
        if preview != "(empty)":
            return preview
    return "(empty)"


def _fallback_step_summary(trace: Trace, step_id: int) -> str:
    cached_summary = get_cached_step_semantic_summary(trace, step_id)
    if cached_summary is not None:
        return f"Step {step_id} summary:\n{cached_summary}"

    index = step_id - 1
    record = trace.get(index)
    diffed = trace.get_diffed(index)
    step_name = f" `{record.name}`" if record.name else ""
    input_chars = blocks_char_count(diffed.new_input_blocks)
    output_chars = blocks_char_count(record.output_blocks)
    return (
        f"Step {step_id} summary:\n"
        f"This{step_name} step takes {input_chars} input chars and produces {output_chars} output chars. "
        f"Specific input: {_preview_blocks(diffed.new_input_blocks)}. "
        f"Specific output: {_preview_blocks(record.output_blocks)}."
    )


def _generate_summary(trace: Trace) -> str:
    """Do the actual work: overview + per-step summaries + synthesis."""
    t0 = time.monotonic()
    base_tag = _prefetch_tag(trace)
    logger.info("%s start steps=%d", base_tag, len(trace))

    try:
        overview = get_trace_overview(trace)
        logger.info(
            "%s overview ready chars=%d elapsed=%.1fs",
            _prefetch_tag(trace, phase="overview"),
            len(overview),
            time.monotonic() - t0,
        )

        summaries_by_step = {}
        pending_steps = []
        for step_id in range(1, len(trace) + 1):
            cached_summary = get_cached_step_semantic_summary(trace, step_id)
            if cached_summary is not None:
                summaries_by_step[step_id] = f"Step {step_id} summary:\n{cached_summary}"
            else:
                pending_steps.append(step_id)

        logger.info(
            "%s budget=%.1fs cached=%d pending=%d",
            _prefetch_tag(trace, phase="steps_budget"),
            _STEP_SUMMARY_BUDGET_SECONDS,
            len(summaries_by_step),
            len(pending_steps),
        )

        completed = len(summaries_by_step)
        future_to_step = {}
        pool = None
        try:
            if pending_steps:
                max_workers = min(len(pending_steps), _STEP_SUMMARY_MAX_WORKERS)
                pool = ThreadPoolExecutor(max_workers=max_workers)
                future_to_step = {
                    pool.submit(_summarize_step_semantically, trace, step_id): step_id
                    for step_id in pending_steps
                }
                deadline = time.monotonic() + _STEP_SUMMARY_BUDGET_SECONDS

                while future_to_step:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    done, _ = wait(
                        tuple(future_to_step),
                        timeout=remaining,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done:
                        break
                    for future in done:
                        step_id = future_to_step.pop(future)
                        try:
                            summaries_by_step[step_id] = future.result()
                        except Exception:
                            logger.exception(
                                "%s semantic summary failed; using fallback",
                                _prefetch_tag(trace, phase="step", step=step_id),
                            )
                            summaries_by_step[step_id] = _fallback_step_summary(trace, step_id)
                        completed += 1
                        logger.info(
                            "%s completed=%d/%d latest_step=%d elapsed=%.1fs",
                            _prefetch_tag(trace, phase="steps_progress"),
                            completed,
                            len(trace),
                            step_id,
                            time.monotonic() - t0,
                        )
        finally:
            if pool is not None:
                pool.shutdown(wait=False, cancel_futures=True)

        if future_to_step:
            fallback_steps = sorted(future_to_step.values())
            logger.warning(
                "%s deadline reached after %.1fs fallback=%d steps=%s",
                _prefetch_tag(trace, phase="steps_budget"),
                _STEP_SUMMARY_BUDGET_SECONDS,
                len(fallback_steps),
                fallback_steps,
            )
            for step_id in fallback_steps:
                summaries_by_step[step_id] = _fallback_step_summary(trace, step_id)

        t_summaries = time.monotonic()

        summaries = [summaries_by_step[step_id] for step_id in range(1, len(trace) + 1)]
        combined = f"## Overview\n{overview}\n\n## Step Summaries\n"
        combined += "\n".join(summaries)
        logger.info(
            "%s combined context chars=%d",
            _prefetch_tag(trace, phase="synthesis_input"),
            len(combined),
        )

        result = infer_text(
            [{"role": "system", "content": SYNTHESIZE_SYSTEM},
             {"role": "user", "content": combined}],
            tier="cheap",
            extra_body=NO_THINKING_EXTRA_BODY,
            max_tokens=_SYNTHESIS_MAX_TOKENS,
        )
        t_synth = time.monotonic()

        logger.info(
            "%s done summary_chars=%d per_step=%.1fs synthesis=%.1fs total=%.1fs",
            base_tag,
            len(result),
            t_summaries - t0,
            t_synth - t_summaries,
            t_synth - t0,
        )
        return result
    except Exception:
        logger.exception("%s failed after %.1fs", base_tag, time.monotonic() - t0)
        raise


def summarize_trace(trace: Trace) -> str:
    if trace.prefetched_summary:
        return trace.prefetched_summary

    result = _generate_summary(trace)
    trace.prefetched_summary = result
    return result
