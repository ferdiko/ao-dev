"""Compatibility wrapper for the old get_summary entrypoint."""

from .get_step_overview import get_step_overview


def get_summary(trace, step_id=None) -> str:
    return get_step_overview(trace, step_id=step_id)
