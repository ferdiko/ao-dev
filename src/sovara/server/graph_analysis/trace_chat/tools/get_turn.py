"""get_turn tool — returns content for a specific turn with view options."""

import json

from ..utils.trace import Trace, format_messages


def get_turn(trace: Trace, **params) -> str:
    turn_id = params.get("turn_id")
    if turn_id is None:
        return "Error: 'turn_id' parameter is required."
    try:
        turn_id = int(turn_id)
    except (TypeError, ValueError):
        return f"Error: 'turn_id' must be an integer, got '{turn_id}'."

    if turn_id < 0 or turn_id >= len(trace):
        return f"Error: turn_id {turn_id} out of range (0–{len(trace) - 1})."

    view = params.get("view", "full")
    if view not in ("full", "diff", "output"):
        return f"Error: view must be 'full', 'diff', or 'output', got '{view}'."

    record = trace.get(turn_id)
    diffed = trace.get_diffed(turn_id)

    if view == "output":
        return _format_output(turn_id, record, diffed)
    elif view == "diff":
        return _format_diff(turn_id, record, diffed, trace)
    else:
        return _format_full(turn_id, record, diffed)


def _header(turn_id, diffed) -> str:
    parts = [f"=== Turn {turn_id} ==="]
    if diffed.model_or_tool:
        parts.append(f"Model/Tool: {diffed.model_or_tool}")
    return "\n".join(parts)


def _output_str(record) -> str:
    if isinstance(record.output, str):
        return record.output
    return json.dumps(record.output, indent=2)


def _format_output(turn_id, record, diffed) -> str:
    return f"{_header(turn_id, diffed)}\n\n{_output_str(record)}"


def _format_full(turn_id, record, diffed) -> str:
    prompt = format_messages(record.input, system_prompt=record.system_prompt)
    output = _output_str(record)
    return f"{_header(turn_id, diffed)}\n\n--- INPUT ---\n{prompt}\n\n--- OUTPUT ---\n{output}"


def _format_diff(turn_id, record, diffed, trace) -> str:
    lines = [_header(turn_id, diffed)]

    # System prompt reference
    if diffed.prompt_id:
        if diffed.prompt_is_new:
            lines.append(f"System prompt [{diffed.prompt_id}] (first occurrence, {len(record.system_prompt)} chars)")
            lines.append(record.system_prompt)
        else:
            lines.append(f"System prompt [{diffed.prompt_id}] (same as earlier turns)")
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
