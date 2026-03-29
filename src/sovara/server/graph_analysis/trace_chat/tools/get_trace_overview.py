"""get_trace_overview tool — returns a structured, diff-aware summary of the trace."""

from ..utils.trace import Trace, blocks_char_count
from .get_step_overview import get_cached_step_semantic_summary


def get_trace_overview(trace: Trace) -> str:
    records = trace.records
    diffed = trace.diffed
    registry = trace.prompt_registry
    prompt_turns = trace.prompt_turns()

    num_steps = len(records)
    num_conversations = len(prompt_turns)
    lines = [
        f"Trace: {num_steps} steps, {num_conversations} conversation(s)",
    ]

    # System prompt registry
    # TODO: This would probably be very helpful but let's leave it out
    # until we figure out a good way how to include this (might also 
    # want to include in pre-fetched summary).
    # if registry:
    #     lines.append("")
    #     lines.append("System prompts:")
    #     for pid, text in registry.items():
    #         steps = [t + 1 for t in prompt_turns.get(pid, [])]
    #         preview = text[:100].replace("\n", " ")
    #         if len(text) > 100:
    #             preview += "..."
    #         lines.append(f'  [{pid}] ({len(text)} chars) "{preview}" — steps {steps}')

    # Per-step breakdown
    lines.append("")
    for dr in diffed:
        record = trace.get(dr.index)
        cached_summary = get_cached_step_semantic_summary(trace, dr.index + 1)
        parts = [
            f"Step {dr.index + 1}",
            dr.name or "unnamed",
            f"{blocks_char_count(dr.new_input_blocks)} input chars (diff)",
            f"{blocks_char_count(record.output_blocks)} output chars",
        ]
        if cached_summary:
            parts.append(cached_summary)
        lines.append(" | ".join(parts))

    return "\n".join(lines)
