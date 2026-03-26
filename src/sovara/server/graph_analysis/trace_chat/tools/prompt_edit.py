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

def _resolve_turn(trace: Trace, turn_index) -> Tuple[int, Optional[str]]:
    """Resolve and validate turn_index. Returns (turn_index, error_or_None).

    If turn_index is omitted and only one prompt exists, defaults to the
    first turn that introduced it.
    """
    if turn_index is not None:
        try:
            turn_index = int(turn_index)
        except (TypeError, ValueError):
            return -1, "Invalid turn_index: must be an integer."
        if turn_index < 0 or turn_index >= len(trace.records):
            return -1, f"turn_index {turn_index} out of range (0–{len(trace.records) - 1})."
        return turn_index, None

    # Auto-resolve: find the first turn that introduced the single prompt
    registry = trace.prompt_registry
    if len(registry) == 0:
        return -1, "No system prompts found. Specify turn_index."
    if len(registry) == 1:
        # Find the first turn where prompt_is_new=True
        for d in trace.diffed:
            if d.prompt_is_new:
                return d.index, None
        return 0, None  # fallback

    lines = ["Multiple prompts found. Specify turn_index for the turn to edit:"]
    for pid, text in registry.items():
        turns = [str(d.index) for d in trace.diffed if d.prompt_id == pid and d.prompt_is_new]
        preview = text[:80].replace("\n", " ")
        lines.append(f"  [{pid}] first at turn {', '.join(turns)}: \"{preview}...\"")
    return -1, "\n".join(lines)


def _get_sections(trace: Trace, turn_index: int, model: str) -> PromptSections:
    """Get or create cached PromptSections for a turn."""
    cache_key = f"turn:{turn_index}"
    if cache_key in trace.prompt_sections_cache:
        return trace.prompt_sections_cache[cache_key]

    sections = flatten_turn(trace, turn_index, model)
    ps = PromptSections(prompt_id=str(turn_index), sections=sections, labeled=True)
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


def _write_back(trace: Trace, turn_index: int, ps: PromptSections) -> str:
    """Write edited sections back to DB, dispatching by section type."""
    diff = trace.diffed[turn_index]
    results = []

    # System prompt sections → all turns sharing this prompt
    sys_sections = [s for s in ps.sections if s.msg_index == -1]
    if sys_sections and diff.prompt_id:
        trace.prompt_registry[diff.prompt_id] = "\n\n".join(s.text for s in sys_sections)
        results.append(write_prompt_edit(trace, diff.prompt_id))

    # Message sections → this turn only
    if any(s.msg_index >= 0 for s in ps.sections):
        results.append(write_input_sections_edit(trace, turn_index))

    return results[-1] if results else ""


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def list_sections(trace: Trace, **params) -> str:
    """List all editable sections for a turn."""
    turn_index, err = _resolve_turn(trace, params.get("turn_index"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, turn_index, model)
    if not ps.sections:
        return f"Turn {turn_index} has no editable content."
    return ps.to_table()


def get_section(trace: Trace, **params) -> str:
    """Return the full text of one section."""
    turn_index, err = _resolve_turn(trace, params.get("turn_index"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, turn_index, model)
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
    turn_index, err = _resolve_turn(trace, params.get("turn_index"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, turn_index, model)
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

    logger.info("edit_section turn=%d index=%d instruction=%r", turn_index, index, instruction)

    preview = new_text[:300]
    suffix = "..." if len(new_text) > 300 else ""
    return f"Section {index} edited ({ps.sections[index].label}):\n{preview}{suffix}" + _write_back(trace, turn_index, ps)


def bulk_edit(trace: Trace, **params) -> str:
    """Apply the same editing instruction to every section in parallel."""
    turn_index, err = _resolve_turn(trace, params.get("turn_index"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, turn_index, model)
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

    logger.info("bulk_edit turn=%d instruction=%r", turn_index, instruction)
    return f"Bulk edit applied to {len(ps.sections)} sections of turn {turn_index}. Use list_sections to review." + _write_back(trace, turn_index, ps)


def insert_section(trace: Trace, **params) -> str:
    """Insert a new section after the given index (-1 to prepend)."""
    turn_index, err = _resolve_turn(trace, params.get("turn_index"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, turn_index, model)

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

    logger.info("insert_section turn=%d after=%d", turn_index, after_index)
    return f"Inserted new section at index {after_index + 1} ({new_section.label}). Now {len(ps.sections)} sections." + _write_back(trace, turn_index, ps)


def delete_section(trace: Trace, **params) -> str:
    """Remove a section by index."""
    turn_index, err = _resolve_turn(trace, params.get("turn_index"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, turn_index, model)
    index = params.get("index")
    verr = _validate_index(ps, index)
    if verr:
        return verr
    index = int(index)

    if len(ps.sections) == 1:
        return "Cannot delete the only section."

    ps.push_undo()

    deleted = ps.sections.pop(index)
    logger.info("delete_section turn=%d index=%d label=%r", turn_index, index, deleted.label)
    return f"Deleted section {index} (was: '{deleted.label}'). {len(ps.sections)} sections remain." + _write_back(trace, turn_index, ps)


def move_section(trace: Trace, **params) -> str:
    """Move a section from one index to another."""
    turn_index, err = _resolve_turn(trace, params.get("turn_index"))
    if err:
        return err
    model = params.get("model", "anthropic/claude-sonnet-4-6")
    ps = _get_sections(trace, turn_index, model)

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
    logger.info("move_section turn=%d %d -> %d", turn_index, from_index, to_index)
    return f"Moved section '{section.label}' from index {from_index} to {to_index}." + _write_back(trace, turn_index, ps)


def undo(trace: Trace, **params) -> str:
    """Revert the last edit."""
    turn_index, err = _resolve_turn(trace, params.get("turn_index"))
    if err:
        return err

    cache_key = f"turn:{turn_index}"
    ps = trace.prompt_sections_cache.get(cache_key)
    if ps is None:
        return "No edits to undo."

    if not ps.pop_undo():
        return "Nothing to undo."

    logger.info("undo turn=%d — %d snapshots remain", turn_index, len(ps.undo_stack))
    return f"Undone. Turn {turn_index} reverted to previous state. {len(ps.sections)} sections." + _write_back(trace, turn_index, ps)
