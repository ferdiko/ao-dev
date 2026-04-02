"""Content viewing and structural editing for trace-chat fields."""

import copy
import re
from typing import Optional, Tuple

from ....llm_backend import NO_THINKING_EXTRA_BODY, infer_text
from ..logger import format_log_tags, get_logger
from ..utils.content_items import StepContentItem, build_step_content_items
from ..utils.edit_persist import (
    PersistOutcome,
    write_input_content_edit,
    write_output_content_edit,
    write_edit_content,
)
from ..utils.editable_content import (
    EditableContentState,
    PathContent,
    build_step_path_content,
    format_path,
)
from ..utils.step_ids import resolve_step_index
from ..utils.text_paths import set_text_value
from ..utils.trace import Trace, build_trace_record_from_to_show

logger = get_logger()
_CONTENT_ID_RE = re.compile(r"^c(\d+)$")


def _edit_system(instruction: str) -> str:
    return (
        "Apply the following edit to the user's text. "
        "Make minimal changes and stay faithful to the original wording and structure. "
        "Return only the rewritten text, nothing else.\n\n"
        f"Edit: {instruction}"
    )


def _edit_log_tag(trace: Trace, *, step: int, content_id: str, phase: str = "") -> str:
    fields = {"tool": "edit_content", "step": step, "content_id": content_id}
    if phase:
        fields["phase"] = phase
    return format_log_tags("trace_tool", run_id=trace.run_id or "-", **fields)


def _resolve_step_id(trace: Trace, step_id) -> Tuple[int, Optional[str]]:
    """Resolve and validate step_id (1-based)."""
    index, err = resolve_step_index(trace, step_id)
    if err:
        return -1, err
    return index, None


def _get_editable_content_state(trace: Trace, idx: int) -> EditableContentState:
    cache_key = f"step:{idx}"
    if cache_key in trace.editable_content_cache:
        return trace.editable_content_cache[cache_key]

    state = EditableContentState(paths=build_step_path_content(trace, idx))
    trace.editable_content_cache[cache_key] = state
    return state


def _copy_editable_content_state(state: EditableContentState) -> EditableContentState:
    return EditableContentState(
        paths=copy.deepcopy(state.paths),
        undo_stack=copy.deepcopy(state.undo_stack),
    )


def _resolve_path_content_for_branch(
    state: EditableContentState,
    *,
    path,
    branch: str,
) -> tuple[Optional[PathContent], Optional[str]]:
    for path_entry in state.paths:
        if path_entry.path == path and path_entry.branch == branch:
            return path_entry, None
    return None, f"Path `{format_path(path)}` not found. Call get_step_overview first."


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


def _get_step_content_items(
    trace: Trace,
    idx: int,
    *,
    state: Optional[EditableContentState] = None,
) -> list[StepContentItem]:
    state = state or _get_editable_content_state(trace, idx)
    return build_step_content_items(state.paths)


def _resolve_content_item(
    trace: Trace,
    idx: int,
    state: EditableContentState,
    *,
    content_id,
    path: Optional[str] = None,
) -> tuple[Optional[StepContentItem], Optional[PathContent], Optional[str]]:
    normalized_content_id, err = _resolve_content_id(content_id)
    if err:
        return None, None, err
    if normalized_content_id is None:
        return None, None, "Missing required parameter: content_id"

    item = next(
        (candidate for candidate in _get_step_content_items(trace, idx, state=state) if candidate.content_id == normalized_content_id),
        None,
    )
    if item is None:
        return None, None, f"content_id {normalized_content_id} not found in step {idx + 1}."

    if path is not None and item.path != path:
        return None, None, (
            f"content_id {normalized_content_id} refers to `{item.display_path}`, "
            f"not `{format_path(path)}`."
        )

    path_entry, err = _resolve_path_content_for_branch(state, path=item.path, branch=item.branch)
    if err:
        return None, None, err
    return item, path_entry, None


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


def _apply_editable_content_state_to_trace(trace: Trace, idx: int, state: EditableContentState) -> None:
    record = trace.records[idx]
    input_to_show = copy.deepcopy(record.input_to_show)
    output_to_show = copy.deepcopy(record.output_to_show)
    shared_prompt_entries = [
        path_entry for path_entry in state.paths
        if path_entry.shared_prompt and path_entry.shared_prompt_id
    ]
    affected_indices = {idx}

    for path_entry in state.paths:
        if path_entry.shared_prompt:
            continue
        target = output_to_show if path_entry.branch == "output" else input_to_show
        set_text_value(target, path_entry.path, path_entry.codec, path_entry.text, strict=True)
    _rebuild_record(trace, idx, input_to_show=input_to_show, output_to_show=output_to_show)

    for path_entry in shared_prompt_entries:
        for rec_idx, other_record in enumerate(trace.records):
            if other_record.prompt_key != path_entry.shared_prompt_id or not other_record.prompt_path:
                continue
            other_input_to_show = copy.deepcopy(other_record.input_to_show)
            set_text_value(
                other_input_to_show,
                other_record.prompt_path,
                other_record.prompt_codec or path_entry.codec,
                path_entry.text,
                strict=True,
            )
            _rebuild_record(trace, rec_idx, input_to_show=other_input_to_show)
            affected_indices.add(rec_idx)

    trace.refresh_after_edit(affected_indices, keep_editable_content_for=idx)
    trace.editable_content_cache[f"step:{idx}"] = state


def _changed_branches(
    before: Optional[EditableContentState],
    after: EditableContentState,
) -> set[str]:
    if before is None:
        return {path_entry.branch for path_entry in after.paths}

    def _snapshot(state: EditableContentState) -> dict[tuple[str, str], tuple[str, ...]]:
        return {
            (path_entry.branch, path_entry.path): tuple(path_entry.paragraphs)
            for path_entry in state.paths
        }

    before_snapshot = _snapshot(before)
    after_snapshot = _snapshot(after)
    changed: set[str] = set()
    for branch, path in set(before_snapshot) | set(after_snapshot):
        if before_snapshot.get((branch, path)) != after_snapshot.get((branch, path)):
            changed.add(branch)
    return changed


def _write_back(
    trace: Trace,
    idx: int,
    state: EditableContentState,
    *,
    modified_branches: Optional[set[str]] = None,
) -> PersistOutcome:
    modified_branches = modified_branches or {path_entry.branch for path_entry in state.paths}
    if not trace.run_id:
        _apply_editable_content_state_to_trace(trace, idx, state)
        return PersistOutcome(ok=True)

    results: list[PersistOutcome] = []
    if "input" in modified_branches:
        for path_entry in state.paths:
            if path_entry.branch == "input" and path_entry.shared_prompt and path_entry.shared_prompt_id:
                results.append(write_edit_content(
                    trace,
                    path_entry.shared_prompt_id,
                    path_entry.path,
                    path_entry.codec,
                    path_entry.text,
                ))
                break
        if any(path_entry.branch == "input" and not path_entry.shared_prompt for path_entry in state.paths):
            results.append(write_input_content_edit(trace, idx, state))
    if "output" in modified_branches:
        if any(path_entry.branch == "output" for path_entry in state.paths):
            results.append(write_output_content_edit(trace, idx, state))

    message = next((result.message for result in reversed(results) if result.message), "")
    if any(not result.ok for result in results):
        return PersistOutcome(ok=False, message=message)

    _apply_editable_content_state_to_trace(trace, idx, state)
    return PersistOutcome(ok=True, message=message)


def get_content_unit(trace, step_id=None, content_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err
    state = _get_editable_content_state(trace, idx)
    item, path_entry, err = _resolve_content_item(trace, idx, state, content_id=content_id)
    if err:
        return err
    return f"[content_id={item.content_id}] `{path_entry.display_path}`:\n{path_entry.paragraphs[item.paragraph_index or 0]}"


def edit_content(trace, instruction, step_id=None, content_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err
    state = _copy_editable_content_state(_get_editable_content_state(trace, idx))
    item, path_entry, err = _resolve_content_item(
        trace,
        idx,
        state,
        content_id=content_id,
    )
    if err:
        return err

    paragraph = item.paragraph_index or 0
    state.push_undo()
    source_text = path_entry.paragraphs[paragraph]
    system_prompt = _edit_system(instruction)
    prompt_tag = _edit_log_tag(
        trace,
        step=idx + 1,
        content_id=str(content_id),
        phase="llm_prompt",
    )
    logger.debug("%s system:\n%s", prompt_tag, system_prompt)
    logger.debug("%s user:\n%s", prompt_tag, source_text)
    new_text = infer_text(
        [{"role": "user", "content": source_text}],
        system=system_prompt,
        tier="expensive",
        extra_body=NO_THINKING_EXTRA_BODY,
        max_tokens=1024,
    ).strip()

    path_entry.paragraphs[paragraph] = new_text

    logger.info(
        "edit_content step=%d path=%s content_id=%s instruction=%r",
        idx + 1,
        path_entry.path,
        content_id,
        instruction,
    )

    preview = new_text[:300] + ("..." if len(new_text) > 300 else "")
    outcome = _write_back(trace, idx, state, modified_branches={path_entry.branch})
    if not outcome.ok:
        return outcome.message.strip() or "Error: failed to write to database."
    return f"Edited content_id={content_id} in `{path_entry.display_path}`:\n{preview}" + outcome.message


def delete_content_unit(trace, step_id=None, content_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err
    state = _copy_editable_content_state(_get_editable_content_state(trace, idx))
    item, path_entry, err = _resolve_content_item(
        trace,
        idx,
        state,
        content_id=content_id,
    )
    if err:
        return err
    paragraph = item.paragraph_index or 0
    if len(path_entry.paragraphs) == 1:
        return "Cannot delete the only content unit in this path. Use edit_content to clear or rewrite it."

    state.push_undo()
    deleted = path_entry.paragraphs.pop(paragraph)
    logger.info(
        "delete_content_unit step=%d path=%s content_id=%s",
        idx + 1,
        path_entry.path,
        content_id,
    )
    preview = deleted[:120] + ("..." if len(deleted) > 120 else "")
    outcome = _write_back(trace, idx, state, modified_branches={path_entry.branch})
    if not outcome.ok:
        return outcome.message.strip() or "Error: failed to write to database."
    return f"Deleted content_id={content_id} from `{path_entry.display_path}`: {preview}" + outcome.message


def undo(trace: Trace, step_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err

    cache_key = f"step:{idx}"
    current = trace.editable_content_cache.get(cache_key)
    state = _copy_editable_content_state(current) if current is not None else None
    if state is None:
        return "No edits to undo."
    before = _copy_editable_content_state(state)
    if not state.pop_undo():
        return "Nothing to undo."

    logger.info("undo step=%d — %d snapshots remain", idx + 1, len(state.undo_stack))
    changed_branches = _changed_branches(before, state)
    outcome = _write_back(trace, idx, state, modified_branches=changed_branches)
    if not outcome.ok:
        return outcome.message.strip() or "Error: failed to write to database."
    return f"Undone. Step {idx + 1} reverted to previous state." + outcome.message
