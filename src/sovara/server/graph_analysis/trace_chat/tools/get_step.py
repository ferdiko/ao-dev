"""get_step tool — returns content for a specific step with view options."""

from ..utils.step_ids import resolve_step_index
from ..utils.trace import Trace, render_record_markdown


def get_step(trace: Trace, step_id, view="full") -> str:
    index, err = resolve_step_index(trace, step_id)
    if err:
        return err

    if view not in ("full", "diff", "output"):
        return f"Error: view must be 'full', 'diff', or 'output', got '{view}'."

    record = trace.get(index)
    diffed = trace.get_diffed(index)

    return render_record_markdown(record, diffed, view=view)
