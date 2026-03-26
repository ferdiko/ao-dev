"""get_overview tool — returns a structured, diff-aware summary of the trace."""

import json

from ..utils.trace import Trace


def get_overview(trace: Trace, **_params) -> str:
    records = trace.records
    diffed = trace.diffed
    registry = trace.prompt_registry
    prompt_turns = trace.prompt_turns()

    num_steps = len(records)
    num_conversations = len(prompt_turns)
    num_standalone = sum(1 for d in diffed if d.prompt_id is None)

    lines = [f"Trace: {num_steps} steps, {num_conversations} conversation(s), {num_standalone} standalone"]

    # System prompt registry
    if registry:
        lines.append("")
        lines.append("System prompts:")
        for pid, text in registry.items():
            steps = [t + 1 for t in prompt_turns.get(pid, [])]
            preview = text[:100].replace("\n", " ")
            if len(text) > 100:
                preview += "..."
            lines.append(f'  [{pid}] ({len(text)} chars) "{preview}" — steps {steps}')

    # Per-step breakdown
    lines.append("")
    for dr in diffed:
        parts = [f"Step {dr.index + 1}:"]

        # Model/tool
        parts.append(dr.model_or_tool or "unspecified")

        # Prompt info
        if dr.prompt_id:
            if dr.prompt_is_new:
                parts.append(f"| prompt={dr.prompt_id} (new)")
            else:
                new_count = len(dr.new_messages)
                parts.append(f"| prompt={dr.prompt_id} (cont, +{new_count} new of {dr.total_messages})")
        else:
            parts.append("| (no prompt)")

        # Message count
        parts.append(f"| {dr.total_messages} msgs")

        # Output size
        out_str = dr.output if isinstance(dr.output, str) else json.dumps(dr.output)
        parts.append(f"| output: {len(out_str)} chars")

        # Label if present
        if dr.label is not None:
            parts.append(f"| label: {dr.label}")

        lines.append(" ".join(parts))

    return "\n".join(lines)
