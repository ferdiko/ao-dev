"""Section-level viewing, editing, and undo for system prompts and input messages."""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple

from ..utils.edit_persist import write_prompt_edit, write_input_sections_edit
from ..utils.llm_backend import infer_text
from ..utils.prompt_sections import PromptSections, Section, label_sections, flatten_turn
from ..utils.trace import Trace

logger = logging.getLogger("sovara_agent")

def _edit_system(instruction: str) -> str:
    return (
        "Apply the following edit to the user's text. "
        "Make minimal changes — stay faithful to the original wording and structure. "
        "Return only the rewritten text, nothing else.\n\n"
        f"Edit: {instruction}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_step_id(trace: Trace, step_id) -> Tuple[int, Optional[str]]:
    """Resolve and validate step_id (1-based). Returns (0-based index, error_or_None).

    If step_id is omitted and only one prompt exists, defaults to the
    first step that introduced it.
    """
    if step_id is not None:
        try:
            step_id = int(step_id)
        except (TypeError, ValueError):
            return -1, "Invalid step_id: must be an integer."
        if step_id < 1 or step_id > len(trace.records):
            return -1, f"step_id {step_id} out of range (1–{len(trace.records)})."
        return step_id - 1, None

    # Auto-resolve: find the first step that introduced the single prompt
    registry = trace.prompt_registry
    if len(registry) == 0:
        return -1, "No system prompts found. Specify step_id."
    if len(registry) == 1:
        # Find the first step where prompt_is_new=True
        for d in trace.diffed:
            if d.prompt_is_new:
                return d.index, None
        return 0, None  # fallback

    lines = ["Multiple prompts found. Specify step_id for the step to edit:"]
    for pid, text in registry.items():
        steps = [str(d.index + 1) for d in trace.diffed if d.prompt_id == pid and d.prompt_is_new]
        preview = text[:80].replace("\n", " ")
        lines.append(f"  [{pid}] first at step {', '.join(steps)}: \"{preview}...\"")
    return -1, "\n".join(lines)


def _get_sections(trace: Trace, idx: int, model: str) -> PromptSections:
    """Get or create cached PromptSections for a step."""
    cache_key = f"step:{idx}"
    if cache_key in trace.prompt_sections_cache:
        return trace.prompt_sections_cache[cache_key]

    sections = flatten_turn(trace, idx, model)
    ps = PromptSections(prompt_id=str(idx), sections=sections, labeled=True)
    trace.prompt_sections_cache[cache_key] = ps
    return ps


def _validate_index(ps: PromptSections, index, param_name="index") -> Optional[str]:
    """Validate a section index. Returns error string or None."""
    if index is None:
        return f"Missing required parameter: {param_name}"
    try:
        index = int(index)
    except (TypeError, ValueError):
        return f"Invalid {param_name}: must be an integer."
    if index < 0 or index >= len(ps.sections):
        return f"Index {index} out of range (0–{len(ps.sections) - 1})."
    return None


def _write_back(trace: Trace, idx: int, ps: PromptSections) -> str:
    """Write edited sections back to DB, dispatching by section type."""
    diff = trace.diffed[idx]
    results = []

    # System prompt sections → all steps sharing this prompt
    sys_sections = [s for s in ps.sections if s.msg_index == -1]
    if sys_sections and diff.prompt_id:
        trace.prompt_registry[diff.prompt_id] = "\n\n".join(s.text for s in sys_sections)
        results.append(write_prompt_edit(trace, diff.prompt_id))

    # Message sections → this step only
    if any(s.msg_index >= 0 for s in ps.sections):
        results.append(write_input_sections_edit(trace, idx))

    return results[-1] if results else ""


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def list_sections(trace: Trace, **params) -> str:
    """List all editable sections for a step."""
    idx, err = _resolve_step_id(trace, params.get("step_id"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, idx, model)
    if not ps.sections:
        return f"Step {idx + 1} has no editable content."
    return ps.to_table()


def get_section(trace: Trace, **params) -> str:
    """Return the full text of one section."""
    idx, err = _resolve_step_id(trace, params.get("step_id"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, idx, model)
    index = params.get("index")
    verr = _validate_index(ps, index)
    if verr:
        return verr
    index = int(index)
    s = ps.sections[index]
    role_tag = f" [{s.role}]" if s.role else ""
    return f"Section {index}{role_tag} ({s.label}):\n{s.text}"


def edit_section(trace: Trace, **params) -> str:
    """Rewrite one section based on a natural-language instruction."""
    idx, err = _resolve_step_id(trace, params.get("step_id"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, idx, model)
    index = params.get("index")
    verr = _validate_index(ps, index)
    if verr:
        return verr
    index = int(index)
    instruction = params.get("instruction")
    if not instruction:
        return "Missing required parameter: instruction"

    ps.push_undo()

    old_text = ps.sections[index].text
    new_text = infer_text(
        [{"role": "user", "content": old_text}],
        model=model,
        system=_edit_system(instruction),
        tier="expensive",
        max_tokens=1024,
    ).strip()
    ps.sections[index].text = new_text

    label_sections([ps.sections[index]], model)

    logger.info("edit_section step=%d index=%d instruction=%r", idx + 1, index, instruction)

    preview = new_text[:300]
    suffix = "..." if len(new_text) > 300 else ""
    return f"Section {index} edited ({ps.sections[index].label}):\n{preview}{suffix}" + _write_back(trace, idx, ps)


def bulk_edit(trace: Trace, **params) -> str:
    """Apply the same editing instruction to every section in parallel."""
    idx, err = _resolve_step_id(trace, params.get("step_id"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, idx, model)
    instruction = params.get("instruction")
    if not instruction:
        return "Missing required parameter: instruction"

    ps.push_undo()

    system = _edit_system(instruction)

    def _edit_one(section: Section) -> str:
        return infer_text(
            [{"role": "user", "content": section.text}],
            model=model,
            system=system,
            tier="expensive",
            max_tokens=1024,
        ).strip()

    with ThreadPoolExecutor() as pool:
        new_texts = list(pool.map(_edit_one, ps.sections))

    for section, new_text in zip(ps.sections, new_texts):
        section.text = new_text

    label_sections(ps.sections, model)

    logger.info("bulk_edit step=%d instruction=%r", idx + 1, instruction)
    return f"Bulk edit applied to {len(ps.sections)} sections of step {idx + 1}. Use list_sections to review." + _write_back(trace, idx, ps)


def insert_section(trace: Trace, **params) -> str:
    """Insert a new section after the given index (-1 to prepend)."""
    idx, err = _resolve_step_id(trace, params.get("step_id"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, idx, model)

    after_index = params.get("after_index")
    if after_index is None:
        return "Missing required parameter: after_index"
    try:
        after_index = int(after_index)
    except (TypeError, ValueError):
        return "Invalid after_index: must be an integer."
    if after_index < -1 or after_index >= len(ps.sections):
        return f"after_index {after_index} out of range (-1–{len(ps.sections) - 1})."

    content = params.get("content")
    if not content:
        return "Missing required parameter: content"

    ps.push_undo()

    # Inherit msg_index and role from the adjacent section
    ref = ps.sections[max(after_index, 0)]
    new_section = Section(text=content, msg_index=ref.msg_index, role=ref.role)
    label_sections([new_section], model)
    ps.sections.insert(after_index + 1, new_section)

    logger.info("insert_section step=%d after=%d", idx + 1, after_index)
    return f"Inserted new section at index {after_index + 1} ({new_section.label}). Now {len(ps.sections)} sections." + _write_back(trace, idx, ps)


def delete_section(trace: Trace, **params) -> str:
    """Remove a section by index."""
    idx, err = _resolve_step_id(trace, params.get("step_id"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, idx, model)
    index = params.get("index")
    verr = _validate_index(ps, index)
    if verr:
        return verr
    index = int(index)

    if len(ps.sections) == 1:
        return "Cannot delete the only section."

    ps.push_undo()

    deleted = ps.sections.pop(index)
    logger.info("delete_section step=%d index=%d label=%r", idx + 1, index, deleted.label)
    return f"Deleted section {index} (was: '{deleted.label}'). {len(ps.sections)} sections remain." + _write_back(trace, idx, ps)


def move_section(trace: Trace, **params) -> str:
    """Move a section from one index to another."""
    idx, err = _resolve_step_id(trace, params.get("step_id"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, idx, model)

    from_index = params.get("from_index")
    to_index = params.get("to_index")
    verr = _validate_index(ps, from_index, "from_index")
    if verr:
        return verr
    verr = _validate_index(ps, to_index, "to_index")
    if verr:
        return verr
    from_index = int(from_index)
    to_index = int(to_index)

    if from_index == to_index:
        return "No move needed — same position."

    ps.push_undo()

    section = ps.sections.pop(from_index)
    ps.sections.insert(to_index, section)
    logger.info("move_section step=%d %d -> %d", idx + 1, from_index, to_index)
    return f"Moved section '{section.label}' from index {from_index} to {to_index}." + _write_back(trace, idx, ps)


def undo(trace: Trace, **params) -> str:
    """Revert the last edit."""
    idx, err = _resolve_step_id(trace, params.get("step_id"))
    if err:
        return err

    cache_key = f"step:{idx}"
    ps = trace.prompt_sections_cache.get(cache_key)
    if ps is None:
        return "No edits to undo."

    if not ps.pop_undo():
        return "Nothing to undo."

    logger.info("undo step=%d — %d snapshots remain", idx + 1, len(ps.undo_stack))
    return f"Undone. Step {idx + 1} reverted to previous state. {len(ps.sections)} sections." + _write_back(trace, idx, ps)
