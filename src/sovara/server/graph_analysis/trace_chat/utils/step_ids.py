"""Shared step-id parsing and validation helpers for trace-chat tools."""

from typing import Optional

from .trace import Trace


def resolve_step_index(
    trace: Trace,
    step_id,
    *,
    required: bool = True,
    error_prefix: str = "Error: ",
) -> tuple[Optional[int], Optional[str]]:
    """Validate a 1-based step_id and return a 0-based index."""
    if step_id is None:
        if required:
            return None, f"{error_prefix}'step_id' parameter is required."
        return None, None

    try:
        parsed_step_id = int(step_id)
    except (TypeError, ValueError):
        return None, f"{error_prefix}'step_id' must be an integer, got '{step_id}'."

    if parsed_step_id < 1 or parsed_step_id > len(trace):
        return None, f"{error_prefix}step_id {parsed_step_id} out of range (1–{len(trace)})."

    return parsed_step_id - 1, None
