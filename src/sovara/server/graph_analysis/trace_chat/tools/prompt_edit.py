"""Path-level viewing, editing, and undo for trace-chat content fields."""

import copy
import logging
import re
from typing import Optional, Tuple

from ....llm_backend import NO_THINKING_EXTRA_BODY, infer_text
from ..utils.content_items import StepContentItem, build_step_content_items
from ..utils.edit_persist import (
    PersistOutcome,
    write_input_sections_edit,
    write_output_sections_edit,
    write_prompt_edit,
)
from ..utils.prompt_sections import (
    PromptSections,
    Section,
    flatten_turn,
    format_paragraph_ref,
    format_path,
)
from ..utils.step_ids import resolve_step_index
from ..utils.text_paths import set_text_value
from ..utils.trace import Trace, build_trace_record_from_to_show

logger = logging.getLogger("sovara_agent")
_PARAGRAPH_REF_RE = re.compile(r"^(.*)::p(\d+)$")
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
    if step_id is not None:
        index, err = resolve_step_index(trace, step_id, error_prefix="")
        if err:
            if err.startswith("'step_id' must be an integer"):
                return -1, "Invalid step_id: must be an integer."
            return -1, err
        return index, None

    registry = trace.prompt_registry
    if len(registry) == 0:
        return -1, "No shared prompt found. Specify step_id."
    if len(registry) == 1:
        for diffed in trace.diffed:
            if diffed.prompt_is_new:
                return diffed.index, None
        return 0, None

    lines = ["Multiple shared prompts found. Specify step_id for the prompt to edit:"]
    for pid, text in registry.items():
        steps = [str(d.index + 1) for d in trace.diffed if d.prompt_id == pid and d.prompt_is_new]
        preview = text[:80].replace("\n", " ")
        lines.append(f"  [{pid}] first at step {', '.join(steps)}: \"{preview}...\"")
    return -1, "\n".join(lines)


def _get_sections(trace: Trace, idx: int) -> PromptSections:
    cache_key = f"step:{idx}"
    if cache_key in trace.prompt_sections_cache:
        return trace.prompt_sections_cache[cache_key]

    ps = PromptSections(prompt_id=str(idx), sections=flatten_turn(trace, idx))
    trace.prompt_sections_cache[cache_key] = ps
    return ps


def _copy_sections(ps: PromptSections) -> PromptSections:
    return PromptSections(
        prompt_id=ps.prompt_id,
        sections=copy.deepcopy(ps.sections),
        undo_stack=copy.deepcopy(ps.undo_stack),
    )


def _parse_path_reference(path) -> tuple[Optional[str], Optional[int], Optional[str]]:
    if path is None:
        return None, None, None

    normalized = str(path).strip()
    if not normalized:
        return None, None, None

    match = _PARAGRAPH_REF_RE.fullmatch(normalized)
    if match:
        base_path = match.group(1)
        if base_path == "<root>":
            base_path = ""
        return base_path, int(match.group(2)), None

    if normalized == "<root>":
        normalized = ""
    return normalized, None, None


def _resolve_section(ps: PromptSections, *, path) -> tuple[Optional[Section], Optional[str]]:
    matches = [section for section in ps.sections if section.path == path]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, (
            f"Path `{format_path(path)}` is ambiguous across input/output. "
            "Use content_id from get_step_overview."
        )
    return None, f"Path `{format_path(path)}` not found. Call get_step_overview first."


def _resolve_section_for_branch(
    ps: PromptSections,
    *,
    path,
    branch: str,
) -> tuple[Optional[Section], Optional[str]]:
    for section in ps.sections:
        if section.path == path and section.branch == branch:
            return section, None
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
    ps: Optional[PromptSections] = None,
) -> list[StepContentItem]:
    ps = ps or _get_sections(trace, idx)
    return build_step_content_items(ps.sections)


def _resolve_content_item(
    trace: Trace,
    idx: int,
    ps: PromptSections,
    *,
    content_id,
    path: Optional[str] = None,
) -> tuple[Optional[StepContentItem], Optional[Section], Optional[str]]:
    normalized_content_id, err = _resolve_content_id(content_id)
    if err:
        return None, None, err
    if normalized_content_id is None:
        return None, None, "Missing required parameter: content_id"

    item = next(
        (candidate for candidate in _get_step_content_items(trace, idx, ps=ps) if candidate.content_id == normalized_content_id),
        None,
    )
    if item is None:
        return None, None, f"content_id {normalized_content_id} not found in step {idx + 1}."

    if path is not None and item.path != path:
        return None, None, (
            f"content_id {normalized_content_id} refers to `{item.display_path}`, "
            f"not `{format_path(path)}`."
        )

    section, err = _resolve_section_for_branch(ps, path=item.path, branch=item.branch)
    if err:
        return None, None, err
    return item, section, None


def _resolve_paragraph(
    section: Section,
    paragraph,
    *,
    required: bool = False,
    inferred: Optional[int] = None,
    param_name: str = "paragraph",
    min_index: int = 0,
    ) -> tuple[Optional[int], Optional[str]]:
    if inferred is not None and paragraph is not None:
        try:
            parsed = int(paragraph)
        except (TypeError, ValueError):
            return None, f"Invalid {param_name}: must be an integer."
        if parsed != inferred:
            return None, f"Conflicting {param_name} and path reference."
        paragraph = parsed

    if paragraph is None:
        paragraph = inferred

    if paragraph is None:
        if required:
            return None, f"Missing required parameter: {param_name}"
        return None, None
    try:
        paragraph = int(paragraph)
    except (TypeError, ValueError):
        return None, f"Invalid {param_name}: must be an integer."
    if paragraph < min_index or paragraph >= len(section.paragraphs):
        return None, (
            f"{param_name} {paragraph} out of range "
            f"({min_index}–{len(section.paragraphs) - 1})."
        )
    return paragraph, None


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


def _apply_sections_to_trace(trace: Trace, idx: int, ps: PromptSections) -> None:
    record = trace.records[idx]
    input_to_show = copy.deepcopy(record.input_to_show)
    output_to_show = copy.deepcopy(record.output_to_show)
    shared_prompt_sections = [section for section in ps.sections if section.shared_prompt and section.prompt_id]
    affected_indices = {idx}

    for section in ps.sections:
        if section.shared_prompt:
            continue
        target = output_to_show if section.branch == "output" else input_to_show
        set_text_value(target, section.path, section.codec, section.text, strict=True)
    _rebuild_record(trace, idx, input_to_show=input_to_show, output_to_show=output_to_show)

    for section in shared_prompt_sections:
        for rec_idx, other_record in enumerate(trace.records):
            if other_record.prompt_key != section.prompt_id or not other_record.prompt_path:
                continue
            other_input_to_show = copy.deepcopy(other_record.input_to_show)
            set_text_value(
                other_input_to_show,
                other_record.prompt_path,
                other_record.prompt_codec or section.codec,
                section.text,
                strict=True,
            )
            _rebuild_record(trace, rec_idx, input_to_show=other_input_to_show)
            affected_indices.add(rec_idx)

    trace.refresh_after_edit(affected_indices, keep_prompt_sections_for=idx)
    trace.prompt_sections_cache[f"step:{idx}"] = ps


def _changed_branches(before: Optional[PromptSections], after: PromptSections) -> set[str]:
    if before is None:
        return {section.branch for section in after.sections}

    def _snapshot(ps: PromptSections) -> dict[tuple[str, str], tuple[str, ...]]:
        return {
            (section.branch, section.path): tuple(section.paragraphs)
            for section in ps.sections
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
    ps: PromptSections,
    *,
    modified_branches: Optional[set[str]] = None,
) -> PersistOutcome:
    modified_branches = modified_branches or {section.branch for section in ps.sections}
    if not trace.run_id:
        _apply_sections_to_trace(trace, idx, ps)
        return PersistOutcome(ok=True)

    results: list[PersistOutcome] = []
    if "input" in modified_branches:
        for section in ps.sections:
            if section.branch == "input" and section.shared_prompt and section.prompt_id:
                results.append(write_prompt_edit(
                    trace,
                    section.prompt_id,
                    section.path,
                    section.codec,
                    section.text,
                ))
                break
        if any(section.branch == "input" and not section.shared_prompt for section in ps.sections):
            results.append(write_input_sections_edit(trace, idx, ps))
    if "output" in modified_branches:
        if any(section.branch == "output" for section in ps.sections):
            results.append(write_output_sections_edit(trace, idx, ps))

    message = next((result.message for result in reversed(results) if result.message), "")
    if any(not result.ok for result in results):
        return PersistOutcome(ok=False, message=message)

    _apply_sections_to_trace(trace, idx, ps)
    return PersistOutcome(ok=True, message=message)


def list_sections(trace: Trace, step_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err
    ps = _get_sections(trace, idx)
    if not ps.sections:
        return f"Step {idx + 1} has no visible content paths."
    return ps.to_table()


def get_content(trace, path=None, step_id=None, paragraph=None, content_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err
    ps = _get_sections(trace, idx)
    path, inferred_paragraph, err = _parse_path_reference(path)
    if err:
        return err

    if content_id is not None:
        if paragraph is not None or inferred_paragraph is not None:
            return "Use either content_id or paragraph, not both."
        item, section, err = _resolve_content_item(trace, idx, ps, content_id=content_id, path=path)
        if err:
            return err
        return f"[content_id={item.content_id}] `{section.display_path}`:\n{section.paragraphs[item.paragraph_index or 0]}"

    if path is None:
        return "Missing required parameter: path"

    section, err = _resolve_section(ps, path=path)
    if err:
        return err

    paragraph, err = _resolve_paragraph(
        section,
        paragraph,
        inferred=inferred_paragraph,
    )
    if err:
        return err

    tags = []
    if section.role:
        tags.append(section.role)
    if section.shared_prompt:
        tags.append("shared prompt")
    tag_str = f" [{' | '.join(tags)}]" if tags else ""

    if paragraph is not None:
        return (
            f"`{section.paragraph_ref(paragraph)}`{tag_str}:\n"
            f"{section.paragraphs[paragraph]}"
        )

    lines = [f"Path `{section.display_path}`{tag_str}:"]
    for para_idx, text in enumerate(section.paragraphs):
        lines.append(f"\n`{section.paragraph_ref(para_idx)}`:\n{text}")
    return "\n".join(lines)


def edit_content(trace, instruction, path=None, step_id=None, paragraph=None, content_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err
    ps = _copy_sections(_get_sections(trace, idx))
    path, inferred_paragraph, err = _parse_path_reference(path)
    if err:
        return err

    if content_id is not None:
        if paragraph is not None or inferred_paragraph is not None:
            return "Use either content_id or paragraph, not both."
        item, section, err = _resolve_content_item(
            trace,
            idx,
            ps,
            content_id=content_id,
            path=path,
        )
        if not err:
            paragraph = item.paragraph_index
    else:
        if path is None:
            return "Missing required parameter: path"
        section, err = _resolve_section(ps, path=path)
        if err:
            return err
        paragraph, err = _resolve_paragraph(
            section,
            paragraph,
            inferred=inferred_paragraph,
        )
    if err:
        return err

    ps.push_undo()
    source_text = section.paragraphs[paragraph] if paragraph is not None else section.text
    new_text = infer_text(
        [{"role": "user", "content": source_text}],
        system=_edit_system(instruction),
        tier="expensive",
        extra_body=NO_THINKING_EXTRA_BODY,
        max_tokens=1024,
    ).strip()

    if paragraph is not None:
        section.paragraphs[paragraph] = new_text
    else:
        section.text = new_text

    logger.info(
        "edit_content step=%d path=%s paragraph=%s content_id=%s instruction=%r",
        idx + 1,
        section.path,
        paragraph,
        content_id,
        instruction,
    )

    preview = new_text[:300] + ("..." if len(new_text) > 300 else "")
    if content_id is not None:
        target_ref = f"{section.display_path} content_id={content_id}"
    else:
        target_ref = section.paragraph_ref(paragraph) if paragraph is not None else section.display_path
    outcome = _write_back(trace, idx, ps, modified_branches={section.branch})
    if not outcome.ok:
        return outcome.message.strip() or "Error: failed to write to database."
    return f"Edited `{target_ref}`:\n{preview}" + outcome.message


def insert_content_paragraph(trace, content, path=None, step_id=None, after_paragraph=None, after_content_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err
    ps = _copy_sections(_get_sections(trace, idx))
    path, inferred_paragraph, err = _parse_path_reference(path)
    if err:
        return err

    if after_content_id is not None:
        if after_paragraph is not None or inferred_paragraph is not None:
            return "Use either after_content_id or after_paragraph, not both."
        item, section, err = _resolve_content_item(
            trace,
            idx,
            ps,
            content_id=after_content_id,
            path=path,
        )
        if not err:
            after_paragraph = item.paragraph_index
    else:
        if path is None:
            return "Missing required parameter: path"
        section, err = _resolve_section(ps, path=path)
        if err:
            return err
        after_paragraph, err = _resolve_paragraph(
            section,
            after_paragraph,
            required=True,
            inferred=inferred_paragraph,
            param_name="after_paragraph",
            min_index=-1,
        )
    if err:
        return err

    ps.push_undo()
    section.paragraphs.insert(after_paragraph + 1, str(content))
    logger.info("insert_content_paragraph step=%d path=%s after=%d", idx + 1, section.path, after_paragraph)
    inserted_ref = format_paragraph_ref(section.path, after_paragraph + 1)
    outcome = _write_back(trace, idx, ps, modified_branches={section.branch})
    if not outcome.ok:
        return outcome.message.strip() or "Error: failed to write to database."
    return f"Inserted paragraph `{inserted_ref}`." + outcome.message


def delete_content_paragraph(trace, path=None, step_id=None, paragraph=None, content_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err
    ps = _copy_sections(_get_sections(trace, idx))
    path, inferred_paragraph, err = _parse_path_reference(path)
    if err:
        return err

    if content_id is not None:
        if paragraph is not None or inferred_paragraph is not None:
            return "Use either content_id or paragraph, not both."
        item, section, err = _resolve_content_item(
            trace,
            idx,
            ps,
            content_id=content_id,
            path=path,
        )
        if not err:
            paragraph = item.paragraph_index
    else:
        if path is None:
            return "Missing required parameter: path"
        section, err = _resolve_section(ps, path=path)
        if err:
            return err
        paragraph, err = _resolve_paragraph(
            section,
            paragraph,
            required=True,
            inferred=inferred_paragraph,
        )
    if err:
        return err
    if len(section.paragraphs) == 1:
        return "Cannot delete the only paragraph. Use edit_content to clear or rewrite it."

    ps.push_undo()
    deleted = section.paragraphs.pop(paragraph)
    logger.info("delete_content_paragraph step=%d path=%s paragraph=%d", idx + 1, section.path, paragraph)
    preview = deleted[:120] + ("..." if len(deleted) > 120 else "")
    outcome = _write_back(trace, idx, ps, modified_branches={section.branch})
    if not outcome.ok:
        return outcome.message.strip() or "Error: failed to write to database."
    return f"Deleted `{section.paragraph_ref(paragraph)}`: {preview}" + outcome.message


def move_content_paragraph(trace, to_paragraph, path=None, step_id=None, from_paragraph=None, from_content_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err
    ps = _copy_sections(_get_sections(trace, idx))
    path, inferred_paragraph, err = _parse_path_reference(path)
    if err:
        return err

    if from_content_id is not None:
        if from_paragraph is not None or inferred_paragraph is not None:
            return "Use either from_content_id or from_paragraph, not both."
        item, section, err = _resolve_content_item(
            trace,
            idx,
            ps,
            content_id=from_content_id,
            path=path,
        )
        if not err:
            from_paragraph = item.paragraph_index
    else:
        if path is None:
            return "Missing required parameter: path"
        section, err = _resolve_section(ps, path=path)
        if err:
            return err
        from_paragraph, err = _resolve_paragraph(
            section,
            from_paragraph,
            required=True,
            inferred=inferred_paragraph,
            param_name="from_paragraph",
        )
    if err:
        return err
    to_paragraph, err = _resolve_paragraph(
        section,
        to_paragraph,
        required=True,
        param_name="to_paragraph",
    )
    if err:
        return err

    if from_paragraph == to_paragraph:
        return "No move needed — same paragraph position."

    ps.push_undo()
    paragraph = section.paragraphs.pop(from_paragraph)
    section.paragraphs.insert(to_paragraph, paragraph)
    logger.info(
        "move_content_paragraph step=%d path=%s %d -> %d",
        idx + 1,
        section.path,
        from_paragraph,
        to_paragraph,
    )
    outcome = _write_back(trace, idx, ps, modified_branches={section.branch})
    if not outcome.ok:
        return outcome.message.strip() or "Error: failed to write to database."
    return f"Moved `{section.paragraph_ref(from_paragraph)}` to `{section.paragraph_ref(to_paragraph)}`." + outcome.message


def undo(trace: Trace, step_id=None) -> str:
    idx, err = _resolve_step_id(trace, step_id)
    if err:
        return err

    cache_key = f"step:{idx}"
    current = trace.prompt_sections_cache.get(cache_key)
    ps = _copy_sections(current) if current is not None else None
    if ps is None:
        return "No edits to undo."
    before = _copy_sections(ps)
    if not ps.pop_undo():
        return "Nothing to undo."

    logger.info("undo step=%d — %d snapshots remain", idx + 1, len(ps.undo_stack))
    changed_branches = _changed_branches(before, ps)
    outcome = _write_back(trace, idx, ps, modified_branches=changed_branches)
    if not outcome.ok:
        return outcome.message.strip() or "Error: failed to write to database."
    return f"Undone. Step {idx + 1} reverted to previous state." + outcome.message
