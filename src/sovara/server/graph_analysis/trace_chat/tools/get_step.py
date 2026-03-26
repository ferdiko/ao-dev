"""get_step tool — returns content for a specific step with view options."""

import json

from ..utils.trace import Trace, format_messages


def get_step(trace: Trace, **params) -> str:
    step_id = params.get("step_id")
    if step_id is None:
        return "Error: 'step_id' parameter is required."
    try:
        step_id = int(step_id)
    except (TypeError, ValueError):
        return f"Error: 'step_id' must be an integer, got '{step_id}'."

    if step_id < 1 or step_id > len(trace):
        return f"Error: step_id {step_id} out of range (1–{len(trace)})."

    index = step_id - 1  # Convert to 0-based internal index

    view = params.get("view", "full")
    if view not in ("full", "diff", "output"):
        return f"Error: view must be 'full', 'diff', or 'output', got '{view}'."

    record = trace.get(index)
    diffed = trace.get_diffed(index)

    if view == "output":
        return _format_output(step_id, record, diffed)
    elif view == "diff":
        return _format_diff(step_id, record, diffed, trace)
    else:
        return _format_full(step_id, record, diffed)


def _header(step_id, diffed) -> str:
    parts = [f"=== Step {step_id} ==="]
    if diffed.model_or_tool:
        parts.append(f"Model/Tool: {diffed.model_or_tool}")
    return "\n".join(parts)


def _output_str(record) -> str:
    if isinstance(record.output, str):
        return record.output
    return json.dumps(record.output, indent=2)


def _format_output(step_id, record, diffed) -> str:
    return f"{_header(step_id, diffed)}\n\n{_output_str(record)}"


def _format_full(step_id, record, diffed) -> str:
    prompt = format_messages(record.input, system_prompt=record.system_prompt)
    output = _output_str(record)
    return f"{_header(step_id, diffed)}\n\n--- INPUT ---\n{prompt}\n\n--- OUTPUT ---\n{output}"


def _format_diff(step_id, record, diffed, trace) -> str:
    lines = [_header(step_id, diffed)]

    # System prompt reference
    if diffed.prompt_id:
        if diffed.prompt_is_new:
            lines.append(f"System prompt [{diffed.prompt_id}] (first occurrence, {len(record.system_prompt)} chars)")
            lines.append(record.system_prompt)
        else:
            lines.append(f"System prompt [{diffed.prompt_id}] (same as earlier steps)")
    else:
        lines.append("(no system prompt)")

    # New messages only
    new_count = len(diffed.new_messages)
    total = diffed.total_messages
    if new_count < total:
        lines.append(f"\n--- NEW MESSAGES ({new_count} of {total} total) ---")
    else:
        lines.append(f"\n--- MESSAGES ({total}) ---")

    lines.append(format_messages(diffed.new_messages))

    # Output
    lines.append(f"\n--- OUTPUT ---\n{_output_str(record)}")

    return "\n".join(lines)
