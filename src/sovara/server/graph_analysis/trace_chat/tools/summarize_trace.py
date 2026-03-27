"""summarize_trace tool — one-shot full trace summary, avoiding extra ReAct rounds."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from .get_overview import get_overview
from .get_summary import get_summary
from ..utils.llm_backend import infer_text
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


logger = logging.getLogger("sovara_agent")


def _generate_summary(trace: Trace, model: str) -> str:
    """Do the actual work: overview + per-step summaries + synthesis."""
    t0 = time.monotonic()
    overview = get_overview(trace)

    def _get_one(tid):
        return get_summary(trace, step_id=tid + 1, model=model)

    with ThreadPoolExecutor() as pool:
        summaries = list(pool.map(_get_one, range(len(trace))))
    t_summaries = time.monotonic()

    combined = f"## Overview\n{overview}\n\n## Step Summaries\n"
    combined += "\n".join(summaries)

    result = infer_text(
        [{"role": "system", "content": SYNTHESIZE_SYSTEM},
         {"role": "user", "content": combined}],
        model=model,
        max_tokens=512,
    )
    t_synth = time.monotonic()

    logger.info("Summary profiling: per-step summaries %.1fs, synthesis %.1fs, total %.1fs",
                t_summaries - t0, t_synth - t_summaries, t_synth - t0)
    return result


def summarize_trace(trace: Trace, **params) -> str:
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    cached = trace.prefetched_summaries.get(model)
    if cached:
        return cached

    result = _generate_summary(trace, model)
    trace.prefetched_summaries[model] = result
    return result
