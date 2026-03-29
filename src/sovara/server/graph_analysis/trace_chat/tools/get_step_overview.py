"""get_step_overview tool — compact step overview with content IDs."""

import re
from dataclasses import dataclass

from ....llm_backend import infer_text
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
    "You label text segments from AI agent prompts and inputs. "
    "For each item, write a concrete summary of exactly 4 or 5 words. "
    "Use noun phrases or short descriptive fragments, not full sentences. "
    "Do not mention 'summary', 'segment', 'paragraph', or quote the text. "
    "Return one line per item as '<id>\\t<label>' and nothing else."
)

INLINE_CONTENT_CHAR_LIMIT = 80


@dataclass(frozen=True)
class StepContentSegment:
    content_id: str
    text: str
    summarized: bool


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


def _build_segments(section) -> list[StepContentSegment]:
    if len(section.paragraphs) > 1:
        return [
            StepContentSegment(content_id=f"c{idx}", text=paragraph, summarized=True)
            for idx, paragraph in enumerate(section.paragraphs)
        ]

    text = section.text
    return [StepContentSegment(content_id="c0", text=text, summarized=len(text) >= INLINE_CONTENT_CHAR_LIMIT)]


def _summarize_segments(trace: Trace, step_id: int, sections: list) -> dict[tuple[str, str], str]:
    pending_items: list[tuple[str, str, str]] = []
    for section in sections:
        for segment in _build_segments(section):
            if not segment.summarized:
                continue
            pending_items.append((section.path, segment.content_id, segment.text))

    if not pending_items:
        return {}

    lines = []
    id_map: dict[str, tuple[str, str, str]] = {}
    for idx, (path, content_id, text) in enumerate(pending_items):
        item_id = f"i{idx}"
        id_map[item_id] = (path, content_id, text)
        lines.extend([
            f"{item_id}",
            f"Path: {path or '<root>'}",
            "Text:",
            text or "(empty)",
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

    summaries: dict[tuple[str, str], str] = {}
    for item_id, (path, content_id, text) in id_map.items():
        summaries[(path, content_id)] = parsed.get(item_id) or _fallback_segment_summary(text)
    return summaries


def _build_step_content(trace: Trace, index: int) -> str:
    step_id = index + 1
    semantic_summary = get_or_compute_step_semantic_summary(trace, step_id)
    sections = list(_get_sections(trace, index).sections)
    segment_summaries = _summarize_segments(trace, step_id, sections)
    record = trace.get(index)

    lines = [f"# Step {step_id}"]
    if record.name:
        lines.append(f"Name: {record.name}")
    lines.extend(["", "## Three-Sentence Summary", "", semantic_summary])

    lines.extend(["", "## Input Content", ""])
    if not sections:
        lines.append("This step has no editable input text fields.")
        return "\n".join(lines).strip()

    for section in sections:
        tags = []
        if section.role:
            tags.append(section.role)
        if section.shared_prompt:
            tags.append("shared prompt")
        tag_str = f" [{' | '.join(tags)}]" if tags else ""
        lines.append(f"### `{section.display_path}`{tag_str}")

        segments = _build_segments(section)
        for segment in segments:
            if not segment.summarized:
                rendered = segment.text or "(empty)"
                lines.append(
                    f"- `content_id={segment.content_id}` full content ({len(segment.text)} chars): {rendered}"
                )
                continue

            summary = segment_summaries.get((section.path, segment.content_id)) or _fallback_segment_summary(segment.text)
            lines.append(
                f"- `content_id={segment.content_id}` summarized content ({len(segment.text)} chars): {summary}"
            )

        lines.append(
            "  Load one content unit with "
            f"`get_content(step_id={step_id}, path=\"{section.display_path}\", content_id=\"...\")`."
        )
        lines.append(
            "  Edit one content unit with "
            f"`edit_content(step_id={step_id}, path=\"{section.display_path}\", content_id=\"...\", instruction=\"...\")`."
        )
        lines.append("")

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

    if index in trace.step_overview_cache:
        logger.info("%s cache hit", _content_tag(trace, step=index + 1))
        return trace.step_overview_cache[index]

    result = _build_step_content(trace, index)
    trace.step_overview_cache[index] = result
    return result
