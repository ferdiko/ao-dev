"""get_step_overview tool — compact step overview with content IDs."""

import re

from ....llm_backend import infer_text
from ..utils.content_items import StepContentItem, build_step_content_items
from ..logger import format_log_tags, get_logger
from ..utils.step_ids import resolve_step_index
from ..utils.trace import Trace, render_record_markdown
from .get_step import build_step_summary
from .prompt_edit import _get_sections

logger = get_logger()

STEP_SUMMARIZE_SYSTEM = (
    "You summarize a single step from an AI agent trace. "
    "Write exactly three sentences:\n"
    "1. What is the general goal of this step — what kind of input does it "
    "take and what kind of output does it produce?\n"
    "2. Characterize the specific input in this step.\n"
    "3. Characterize the specific output in this step.\n"
    "Be concise and concrete. No preamble."
)

SEGMENT_SUMMARIZE_SYSTEM = (
    "You label text segments from AI agent traces. "
    "For each item, write a concrete summary of exactly 4 or 5 words. "
    "Use noun phrases or short descriptive fragments, not full sentences. "
    "Do not mention 'summary', 'segment', 'paragraph', or quote the text. "
    "Return one line per item as '<id>\\t<label>' and nothing else."
)


def _content_tag(trace: Trace, *, step: int, phase: str = "") -> str:
    fields = {"tool": "get_step_overview", "step": step}
    if phase:
        fields["phase"] = phase
    return format_log_tags("trace_tool", run_id=trace.run_id or "-", **fields)


def _compact_text(text: str) -> str:
    return " ".join(str(text).split()).strip()


def _fallback_segment_summary(text: str) -> str:
    compact = _compact_text(text)
    if not compact:
        return "(empty content)"
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'/_-]*", compact)
    if not words:
        return compact[:40]
    return " ".join(words[:5])


def _summarize_content_items(trace: Trace, step_id: int, items: list[StepContentItem]) -> dict[str, str]:
    pending_items = [item for item in items if item.summarized]

    if not pending_items:
        return {}

    lines = []
    id_map: dict[str, StepContentItem] = {}
    for idx, item in enumerate(pending_items):
        item_id = f"i{idx}"
        id_map[item_id] = item
        lines.extend([
            f"{item_id}",
            f"Path: {item.display_path}",
            "Text:",
            item.text or "(empty)",
            "",
        ])

    raw = infer_text(
        [{"role": "system", "content": SEGMENT_SUMMARIZE_SYSTEM},
         {"role": "user", "content": "\n".join(lines).strip()}],
        tier="cheap",
        max_tokens=max(128, 24 * len(pending_items)),
    )
    logger.info(
        "%s segment summaries generated items=%d chars=%d",
        _content_tag(trace, step=step_id, phase="segment_summaries"),
        len(pending_items),
        len(raw),
    )

    parsed: dict[str, str] = {}
    for line in raw.splitlines():
        item_id, sep, label = line.partition("\t")
        item_id = item_id.strip()
        label = label.strip()
        if sep and item_id in id_map and label:
            parsed[item_id] = label
    if len(pending_items) == 1 and not parsed:
        only_item_id = next(iter(id_map))
        fallback_label = raw.strip()
        if fallback_label:
            parsed[only_item_id] = fallback_label

    summaries: dict[str, str] = {}
    for item_id, item in id_map.items():
        summaries[item.content_id] = parsed.get(item_id) or _fallback_segment_summary(item.text)
    return summaries


def _render_get_content_call(step_id: int, item: StepContentItem) -> str:
    return (
        f"`get_content(step_id={step_id}, path=\"{item.display_path}\", "
        f"content_id=\"{item.content_id}\")`"
    )


def _render_edit_content_call(step_id: int, item: StepContentItem) -> str:
    return (
        f"`edit_content(step_id={step_id}, path=\"{item.display_path}\", "
        f"content_id=\"{item.content_id}\", instruction=\"...\")`"
    )


def _render_content_items(
    lines: list[str],
    sections,
    items_by_path: dict[tuple[str, str], list[StepContentItem]],
    item_summaries: dict[str, str],
    *,
    step_id: int,
) -> None:
    if not sections:
        lines.append("(empty)")
        return

    for section in sections:
        lines.append(f"### `{section.display_path}`")
        for item in items_by_path.get((section.branch, section.path), []):
            label = "Summarized" if item.summarized else "Full"
            if item.summarized:
                rendered_text = item_summaries.get(item.content_id) or _fallback_segment_summary(item.text)
            else:
                rendered_text = _compact_text(item.text) or "(empty)"
            lines.append(
                f"- [content_id={item.content_id}] {label} content ({len(item.text)} chars): {rendered_text}"
            )
            if item.summarized:
                lines.append(f"  Load unsummarized content with {_render_get_content_call(step_id, item)}.")
            lines.append(f"  Edit this content with {_render_edit_content_call(step_id, item)}.")
            lines.append("")
        lines.append("")


def _build_step_content(trace: Trace, index: int) -> str:
    step_id = index + 1
    semantic_summary = get_cached_step_semantic_summary(trace, step_id)
    sections = list(_get_sections(trace, index).sections)
    record = trace.get(index)
    content_items = build_step_content_items(sections)
    item_summaries = _summarize_content_items(trace, step_id, content_items)
    input_sections = [section for section in sections if section.branch == "input"]
    output_sections = [section for section in sections if section.branch == "output"]
    items_by_path: dict[tuple[str, str], list[StepContentItem]] = {}
    for item in content_items:
        items_by_path.setdefault((item.branch, item.path), []).append(item)

    lines = [f"# Step {step_id}"]
    if record.name:
        lines.append(f"Name: {record.name}")
    if semantic_summary:
        lines.extend(["", "## Summary", "", semantic_summary])

    lines.extend(["", "## Input Content", ""])
    _render_content_items(lines, input_sections, items_by_path, item_summaries, step_id=step_id)

    lines.extend(["", "## Output Content", ""])
    _render_content_items(lines, output_sections, items_by_path, item_summaries, step_id=step_id)

    return "\n".join(lines).strip()


def get_cached_step_semantic_summary(trace: Trace, step_id: int) -> str | None:
    index, err = resolve_step_index(trace, step_id)
    if err:
        raise ValueError(err)

    if index in trace.step_semantic_summary_cache:
        return trace.step_semantic_summary_cache[index]

    record = trace.get(index)
    if record.summary:
        trace.step_semantic_summary_cache[index] = record.summary
        return record.summary

    return None


def get_or_compute_step_semantic_summary(trace: Trace, step_id: int) -> str:
    cached_summary = get_cached_step_semantic_summary(trace, step_id)
    if cached_summary is not None:
        return cached_summary

    index, err = resolve_step_index(trace, step_id)
    if err:
        raise ValueError(err)

    record = trace.get(index)
    log_tag = _content_tag(trace, step=step_id, phase="semantic_summary")

    rendered = render_record_markdown(record, trace.get_diffed(index), view="full")
    structured_summary = build_step_summary(record, rendered_chars=len(rendered))
    semantic_summary = infer_text(
        [{"role": "system", "content": STEP_SUMMARIZE_SYSTEM},
         {"role": "user", "content": structured_summary}],
        tier="cheap",
        max_tokens=256,
    ).strip()
    logger.info("%s generated chars=%d", log_tag, len(semantic_summary))
    trace.step_semantic_summary_cache[index] = semantic_summary
    return semantic_summary


def get_step_overview(trace: Trace, step_id=None) -> str:
    index, err = resolve_step_index(trace, step_id)
    if err:
        return err

    cached_summary = get_cached_step_semantic_summary(trace, index + 1)
    if index in trace.step_overview_cache:
        cached_result = trace.step_overview_cache[index]
        if not cached_summary or "\n## Summary\n" in cached_result:
            logger.info("%s cache hit", _content_tag(trace, step=index + 1))
            return cached_result

    result = _build_step_content(trace, index)
    trace.step_overview_cache[index] = result
    return result
