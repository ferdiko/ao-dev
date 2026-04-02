"""Content viewing and structural editing for trace-chat fields."""

import copy
import re
from typing import Optional, Tuple

from sovara.common.constants import INFERENCE_SERVER_LOG
from sovara.common.logger import create_file_logger

from ....llm_backend import NO_THINKING_EXTRA_BODY, infer_text
from ..cancel import raise_if_cancelled
from ..utils.edit_persist import (
    PersistOutcome,
    write_input_content_edit,
    write_output_content_edit,
)
from ..utils.step_content_view import (
    StepContentView,
    build_step_content_view,
    delete_content_unit_from_view,
    format_dict_path,
    replace_content_unit_text,
    resolve_content_unit,
)
from ..utils.step_ids import resolve_step_index
from ..utils.trace import Trace, build_trace_record_from_to_show

logger = create_file_logger(INFERENCE_SERVER_LOG)
_CONTENT_ID_RE = re.compile(r"^c(\d+)$")


def _edit_system(instruction: str) -> str:
    return (
        "Apply the following edit to the user's text. "
        "Make minimal changes and stay faithful to the original wording and structure. "
        "Return only the rewritten text, nothing else.\n\n"
        f"Edit: {instruction}"
    )


def _resolve_step_id(trace: Trace, step_id) -> Tuple[int, Optional[str]]:
    """Resolve and validate step_id (1-based)."""
    index, err = resolve_step_index(trace, step_id)
    if err:
        return -1, err
    return index, None


def _resolve_content_id(content_id) -> tuple[Optional[str], Optional[str]]:
    if content_id is None:
        return None, None
    normalized = str(content_id).strip()
    if not normalized:
        return None, "Missing required parameter: content_id"
    match = _CONTENT_ID_RE.fullmatch(normalized)
    if not match:
        return None, "Invalid content_id: must look like c0, c1, c2, ..."
    return normalized, None


def _build_step_content_view(trace: Trace, idx: int, *, for_edit: bool = False) -> StepContentView:
    record = trace.records[idx]
    input_to_show = copy.deepcopy(record.input_to_show) if for_edit else record.input_to_show
    output_to_show = copy.deepcopy(record.output_to_show) if for_edit else record.output_to_show
    return build_step_content_view(input_to_show, output_to_show)


def _resolve_view_unit(
    trace: Trace,
    idx: int,
    view: StepContentView,
    *,
    content_id,
):
    normalized_content_id, err = _resolve_content_id(content_id)
    if err:
        return None, err
    if normalized_content_id is None:
        return None, "Missing required parameter: content_id"

    try:
        return resolve_content_unit(view, normalized_content_id), None
    except KeyError:
        return None, f"content_id {normalized_content_id} not found in step {idx + 1}."


def _rebuild_record(
    trace: Trace,
    idx: int,
    *,
    input_to_show: Optional[dict] = None,
    output_to_show: Optional[dict] = None,
) -> None:
    record = trace.records[idx]
    trace.records[idx] = build_trace_record_from_to_show(
        input_to_show if input_to_show is not None else copy.deepcopy(record.input_to_show),
        output_to_show if output_to_show is not None else copy.deepcopy(record.output_to_show),
        index=record.index,
        correct=record.correct,
        label=record.label,
        summary=record.summary,
        name=record.name,
        node_uuid=record.node_uuid,
    )


def _write_back(
    trace: Trace,
    idx: int,
    input_to_show: dict,
    output_to_show: dict,
    *,
    modified_branches: Optional[set[str]] = None,
) -> PersistOutcome:
    modified_branches = modified_branches or set()

    results: list[PersistOutcome] = []
    if trace.run_id:
        if "input" in modified_branches:
            results.append(write_input_content_edit(trace, idx, input_to_show))
        if "output" in modified_branches:
            results.append(write_output_content_edit(trace, idx, output_to_show))

    message = next((result.message for result in reversed(results) if result.message), "")
    if any(not result.ok for result in results):
        return PersistOutcome(ok=False, message=message)

    _rebuild_record(trace, idx, input_to_show=input_to_show, output_to_show=output_to_show)
    trace.refresh_after_edit({idx})
    return PersistOutcome(ok=True, message=message)


def _push_undo_snapshot(trace: Trace, idx: int) -> None:
    record = trace.records[idx]
    trace.edit_undo_stack.setdefault(idx, []).append((
        copy.deepcopy(record.input_to_show),
        copy.deepcopy(record.output_to_show),
    ))


def _pop_undo_snapshot(trace: Trace, idx: int) -> None:
    history = trace.edit_undo_stack.get(idx)
    if not history:
        return
    history.pop()
    if not history:
        trace.edit_undo_stack.pop(idx, None)


def get_content_unit(trace, step_id=None, content_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err

    view = _build_step_content_view(trace, idx)
    unit, err = _resolve_view_unit(trace, idx, view, content_id=content_id)
    if err:
        return err
    return f"[content_id={unit.content_id}] `{format_dict_path(unit.dict_path)}`:\n{unit.text}"


def edit_content(trace, instruction, step_id=None, content_id=None, cancel_event=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err

    view = _build_step_content_view(trace, idx, for_edit=True)
    unit, err = _resolve_view_unit(trace, idx, view, content_id=content_id)
    if err:
        return err

    _push_undo_snapshot(trace, idx)
    source_text = unit.text
    system_prompt = _edit_system(instruction)
    logger.debug(
        "edit_content prompt system run_id=%s step=%d content_id=%s:\n%s",
        trace.run_id or "-",
        idx + 1,
        content_id,
        system_prompt,
    )
    logger.debug(
        "edit_content prompt user run_id=%s step=%d content_id=%s:\n%s",
        trace.run_id or "-",
        idx + 1,
        content_id,
        source_text,
    )
    raise_if_cancelled(cancel_event)
    new_text = infer_text(
        [{"role": "user", "content": source_text}],
        system=system_prompt,
        tier="expensive",
        cancel_event=cancel_event,
        extra_body=NO_THINKING_EXTRA_BODY,
        max_tokens=1024,
    ).strip()

    updated_unit = replace_content_unit_text(view, content_id, new_text)

    logger.info(
        "edit_content step=%d path=%s content_id=%s instruction=%r",
        idx + 1,
        format_dict_path(updated_unit.dict_path),
        content_id,
        instruction,
    )

    preview = new_text[:300] + ("..." if len(new_text) > 300 else "")
    raise_if_cancelled(cancel_event)
    outcome = _write_back(
        trace,
        idx,
        view.input_to_show,
        view.output_to_show,
        modified_branches={updated_unit.input_or_output},
    )
    if not outcome.ok:
        _pop_undo_snapshot(trace, idx)
        return outcome.message.strip() or "Error: failed to write to database."
    return f"Edited content_id={content_id} in `{format_dict_path(updated_unit.dict_path)}`:\n{preview}" + outcome.message


def delete_content_unit(trace, step_id=None, content_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err

    view = _build_step_content_view(trace, idx, for_edit=True)
    unit, err = _resolve_view_unit(trace, idx, view, content_id=content_id)
    if err:
        return err

    _push_undo_snapshot(trace, idx)
    deleted = delete_content_unit_from_view(view, content_id)
    logger.info(
        "delete_content_unit step=%d path=%s content_id=%s",
        idx + 1,
        format_dict_path(unit.dict_path),
        content_id,
    )
    preview = deleted.text[:120] + ("..." if len(deleted.text) > 120 else "")
    outcome = _write_back(
        trace,
        idx,
        view.input_to_show,
        view.output_to_show,
        modified_branches={deleted.input_or_output},
    )
    if not outcome.ok:
        _pop_undo_snapshot(trace, idx)
        return outcome.message.strip() or "Error: failed to write to database."
    return f"Deleted content_id={content_id} from `{format_dict_path(deleted.dict_path)}`: {preview}" + outcome.message


def undo(trace: Trace, step_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err

    history = trace.edit_undo_stack.get(idx)
    if history is None:
        return "No edits to undo."
    if not history:
        return "Nothing to undo."

    previous_input_to_show, previous_output_to_show = history.pop()
    if not history:
        trace.edit_undo_stack.pop(idx, None)

    record = trace.records[idx]
    changed_branches = set()
    if record.input_to_show != previous_input_to_show:
        changed_branches.add("input")
    if record.output_to_show != previous_output_to_show:
        changed_branches.add("output")

    logger.info("undo step=%d — %d snapshots remain", idx + 1, len(history))
    outcome = _write_back(
        trace,
        idx,
        previous_input_to_show,
        previous_output_to_show,
        modified_branches=changed_branches,
    )
    if not outcome.ok:
        trace.edit_undo_stack.setdefault(idx, []).append((
            previous_input_to_show,
            previous_output_to_show,
        ))
        return outcome.message.strip() or "Error: failed to write to database."
    return f"Undone. Step {idx + 1} reverted to previous state." + outcome.message
