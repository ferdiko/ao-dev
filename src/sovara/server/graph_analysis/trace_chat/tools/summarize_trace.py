"""summarize_trace tool — one-shot full trace summary, avoiding extra ReAct rounds."""

import time

from sovara.common.constants import INFERENCE_SERVER_LOG, SCATTER_BUDGET
from sovara.common.logger import create_file_logger

from ....llm_backend import NO_THINKING_EXTRA_BODY, infer_text, scatter_execute
from ..utils.trace import Trace, blocks_char_count, stringify_field
from .get_step_overview import (
    STEP_SUMMARIZE_SYSTEM,
    get_cached_step_semantic_summary,
    get_or_compute_step_semantic_summary,
)
from .get_trace_overview import get_trace_overview

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

logger = create_file_logger(INFERENCE_SERVER_LOG)


def _summarize_step_semantically(trace: Trace, step_id: int) -> str:
    t0 = time.monotonic()
    semantic_summary = get_or_compute_step_semantic_summary(trace, step_id)
    logger.info(
        "summarize_trace step summary ready run_id=%s step=%d elapsed=%.1fs chars=%d",
        trace.run_id or "-",
        step_id,
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


def _prefix_structural_header(summary: str, overview: str) -> str:
    header = next((line.strip() for line in overview.splitlines() if line.strip()), "")
    if not header:
        return summary

    stripped_summary = summary.lstrip()
    if stripped_summary.startswith(header):
        return summary
    if not stripped_summary:
        return header
    return f"{header}\n{summary}"


def _generate_summary(
    trace: Trace,
    step_budget_seconds: float = SCATTER_BUDGET,
) -> str:
    """Do the actual work: overview + per-step summaries + synthesis."""
    t0 = time.monotonic()
    run_id = trace.run_id or "-"
    logger.info("summarize_trace start run_id=%s steps=%d", run_id, len(trace))

    try:
        overview = get_trace_overview(trace)
        logger.info(
            "summarize_trace overview ready run_id=%s chars=%d elapsed=%.1fs",
            run_id,
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
            "summarize_trace step budget run_id=%s budget=%.1fs cached=%d pending=%d",
            run_id,
            step_budget_seconds,
            len(summaries_by_step),
            len(pending_steps),
        )

        completed = len(summaries_by_step)
        if pending_steps:
            def _on_summary_result(step_id: int, _summary: str) -> None:
                nonlocal completed
                completed += 1
                logger.info(
                    "summarize_trace progress run_id=%s completed=%d/%d latest_step=%d elapsed=%.1fs",
                    run_id,
                    completed,
                    len(trace),
                    step_id,
                    time.monotonic() - t0,
                )

            def _on_summary_exception(step_id: int, _exc: Exception) -> None:
                logger.exception(
                    "summarize_trace step summary failed run_id=%s step=%d; using fallback",
                    run_id,
                    step_id,
                )

            def _on_summary_timeout(fallback_steps: list[int]) -> None:
                logger.warning(
                    "summarize_trace step budget timed out run_id=%s after %.1fs fallback=%d steps=%s",
                    run_id,
                    step_budget_seconds,
                    len(fallback_steps),
                    sorted(fallback_steps),
                )

            step_summaries = scatter_execute(
                pending_steps,
                lambda step_id: _summarize_step_semantically(trace, step_id),
                max_workers=min(len(pending_steps), _STEP_SUMMARY_MAX_WORKERS),
                budget_seconds=step_budget_seconds,
                on_result=_on_summary_result,
                on_exception=_on_summary_exception,
                on_timeout=_on_summary_timeout,
            )
            for step_id, semantic_summary in zip(pending_steps, step_summaries):
                summaries_by_step[step_id] = (
                    semantic_summary
                    if semantic_summary is not None
                    else _fallback_step_summary(trace, step_id)
                )

        t_summaries = time.monotonic()

        summaries = [summaries_by_step[step_id] for step_id in range(1, len(trace) + 1)]
        combined = f"## Overview\n{overview}\n\n## Step Summaries\n"
        combined += "\n".join(summaries)
        logger.info(
            "summarize_trace synthesis input run_id=%s chars=%d",
            run_id,
            len(combined),
        )

        result = infer_text(
            [{"role": "system", "content": SYNTHESIZE_SYSTEM},
             {"role": "user", "content": combined}],
            tier="cheap",
            extra_body=NO_THINKING_EXTRA_BODY,
            max_tokens=_SYNTHESIS_MAX_TOKENS,
        )
        result = _prefix_structural_header(result, overview)
        t_synth = time.monotonic()

        logger.info(
            "summarize_trace done run_id=%s summary_chars=%d per_step=%.1fs synthesis=%.1fs total=%.1fs",
            run_id,
            len(result),
            t_summaries - t0,
            t_synth - t_summaries,
            t_synth - t0,
        )
        return result
    except Exception:
        logger.exception("summarize_trace failed run_id=%s after %.1fs", run_id, time.monotonic() - t0)
        raise


def summarize_trace(trace: Trace) -> str:
    if trace.prefetched_summary:
        return trace.prefetched_summary

    result = _generate_summary(trace)
    trace.prefetched_summary = result
    return result
