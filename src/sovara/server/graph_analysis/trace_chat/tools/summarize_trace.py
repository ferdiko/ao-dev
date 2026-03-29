"""summarize_trace tool — one-shot full trace summary, avoiding extra ReAct rounds."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .get_trace_overview import get_trace_overview
from .get_step_overview import STEP_SUMMARIZE_SYSTEM, get_or_compute_step_semantic_summary
from ....llm_backend import infer_text
from ..logger import format_log_tags, get_logger
from ..utils.trace import Trace

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


def _summary_tag(trace: Trace, **fields) -> str:
    return format_log_tags("trace_summary", run_id=trace.run_id or "-", **fields)


def _summarize_step_semantically(trace: Trace, step_id: int) -> str:
    step_tag = _summary_tag(trace, phase="step", step=step_id)
    t0 = time.monotonic()
    semantic_summary = get_or_compute_step_semantic_summary(trace, step_id)
    logger.info(
        "%s semantic summary ready in %.1fs chars=%d",
        step_tag,
        time.monotonic() - t0,
        len(semantic_summary),
    )
    return f"Step {step_id} summary:\n{semantic_summary}"


def _generate_summary(trace: Trace) -> str:
    """Do the actual work: overview + per-step summaries + synthesis."""
    t0 = time.monotonic()
    base_tag = _summary_tag(trace)
    logger.info("%s start steps=%d", base_tag, len(trace))

    try:
        overview = get_trace_overview(trace)
        logger.info(
            "%s overview ready chars=%d elapsed=%.1fs",
            _summary_tag(trace, phase="overview"),
            len(overview),
            time.monotonic() - t0,
        )

        summaries_by_step = {}
        with ThreadPoolExecutor() as pool:
            futures = {
                pool.submit(_summarize_step_semantically, trace, step_id): step_id
                for step_id in range(1, len(trace) + 1)
            }
            for completed, future in enumerate(as_completed(futures), start=1):
                step_id = futures[future]
                summaries_by_step[step_id] = future.result()
                logger.info(
                    "%s completed=%d/%d latest_step=%d elapsed=%.1fs",
                    _summary_tag(trace, phase="steps_progress"),
                    completed,
                    len(trace),
                    step_id,
                    time.monotonic() - t0,
                )
        t_summaries = time.monotonic()

        summaries = [summaries_by_step[step_id] for step_id in range(1, len(trace) + 1)]
        combined = f"## Overview\n{overview}\n\n## Step Summaries\n"
        combined += "\n".join(summaries)
        logger.info(
            "%s combined context chars=%d",
            _summary_tag(trace, phase="synthesis_input"),
            len(combined),
        )

        result = infer_text(
            [{"role": "system", "content": SYNTHESIZE_SYSTEM},
             {"role": "user", "content": combined}],
            max_tokens=512,
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
