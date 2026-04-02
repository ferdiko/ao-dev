"""get_step_overview tool — compact step overview with content IDs."""

import re

from sovara.common.constants import INFERENCE_SERVER_LOG, TRACE_CHAT_SCATTER_BUDGET_SECONDS
from sovara.common.logger import create_file_logger

from ....llm_backend import infer_text, scatter_execute
from ..cancel import raise_if_cancelled
from ..utils.step_content_view import ContentUnit, build_step_content_view, format_dict_path
from ..utils.step_ids import resolve_step_index
from ..utils.trace import Trace, render_record_markdown
from .get_step_snapshot import build_step_summary

logger = create_file_logger(INFERENCE_SERVER_LOG)
_SUMMARY_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\d+[.)]\s*)?`?(i\d+)`?\s*(?:\t|:\s*|\|\s*|-\s+)(.+?)\s*$"
)
_SUMMARY_TIER = "cheap"
_SEGMENT_SUMMARY_MAX_TOKENS = 512
_STEP_SUMMARY_MAX_TOKENS = 2048
_SUMMARY_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}
_SEGMENT_SUMMARY_MAX_WORKERS = 10
_INLINE_CONTENT_CHAR_LIMIT = 80

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


def _should_summarize(text: str) -> bool:
    return len(text) >= _INLINE_CONTENT_CHAR_LIMIT


def _parse_segment_summary_response(raw: str, id_map: dict[str, ContentUnit]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        item_id, sep, label = stripped.partition("\t")
        item_id = item_id.strip().strip("`")
        label = label.strip()
        if sep and item_id in id_map and label:
            parsed[item_id] = label
            continue

        match = _SUMMARY_LINE_RE.match(stripped)
        if match:
            item_id = match.group(1).strip()
            label = match.group(2).strip().strip("`")
            if item_id in id_map and label:
                parsed[item_id] = label

    if len(id_map) == 1 and not parsed:
        only_item_id = next(iter(id_map))
        fallback_label = raw.strip()
        if fallback_label:
            parsed[only_item_id] = fallback_label

    return parsed


def _summarize_one_content_item(
    item: ContentUnit,
    *,
    run_id: str,
    step_id: int,
    item_index: int,
    total: int,
    cancel_event=None,
) -> str | None:
    raise_if_cancelled(cancel_event)
    raw = infer_text(
        [{"role": "system", "content": SEGMENT_SUMMARIZE_SYSTEM},
         {"role": "user", "content": "\n".join([
             "i0",
             f"Path: {format_dict_path(item.dict_path)}",
             "Text:",
             item.text or "(empty)",
         ]).strip()}],
        tier=_SUMMARY_TIER,
        cancel_event=cancel_event,
        extra_body=_SUMMARY_EXTRA_BODY,
        max_tokens=_SEGMENT_SUMMARY_MAX_TOKENS,
    )
    logger.info(
        "get_step_overview segment summary generated run_id=%s step=%d item=%d/%d chars=%d",
        run_id,
        step_id,
        item_index,
        total,
        len(raw),
    )
    parsed = _parse_segment_summary_response(raw, {"i0": item})
    label = parsed.get("i0")
    if not label:
        logger.warning(
            "get_step_overview segment summary parse shortfall run_id=%s step=%d item=%d/%d raw=%r",
            run_id,
            step_id,
            item_index,
            total,
            _compact_text(raw)[:400],
        )
    return label


def _summarize_content_items(
    trace: Trace,
    step_id: int,
    items: list[ContentUnit],
    *,
    cancel_event=None,
) -> dict[str, str]:
    pending_items = [item for item in items if _should_summarize(item.text)]
    run_id = trace.run_id or "-"

    if not pending_items:
        logger.info("get_step_overview segment summaries skipped run_id=%s step=%d items=0", run_id, step_id)
        return {}

    max_workers = min(len(pending_items), _SEGMENT_SUMMARY_MAX_WORKERS)
    logger.info(
        "get_step_overview segment summaries start run_id=%s step=%d items=%d mode=per_item_parallel max_workers=%d",
        run_id,
        step_id,
        len(pending_items),
        max_workers,
    )

    summaries: dict[str, str] = {}
    fallback_count = 0
    total = len(pending_items)
    indexed_items = list(enumerate(pending_items, start=1))

    def _run_one(indexed_item: tuple[int, ContentUnit]) -> str | None:
        item_index, item = indexed_item
        return _summarize_one_content_item(
            item,
            run_id=run_id,
            step_id=step_id,
            item_index=item_index,
            total=total,
            cancel_event=cancel_event,
        )

    def _on_summary_exception(indexed_item: tuple[int, ContentUnit], _exc: Exception) -> None:
        logger.exception(
            "get_step_overview segment summary failed run_id=%s step=%d content_id=%s",
            run_id,
            step_id,
            indexed_item[1].content_id,
        )

    def _on_summary_timeout(timed_out_items: list[tuple[int, ContentUnit]]) -> None:
        fallback_items = sorted(item.content_id for _idx, item in timed_out_items)
        logger.warning(
            "get_step_overview segment summaries timed out run_id=%s step=%d after %.1fs fallback=%d items=%s",
            run_id,
            step_id,
            TRACE_CHAT_SCATTER_BUDGET_SECONDS,
            len(fallback_items),
            fallback_items,
        )

    labels = scatter_execute(
        indexed_items,
        _run_one,
        max_workers=max_workers,
        budget_seconds=TRACE_CHAT_SCATTER_BUDGET_SECONDS,
        cancel_event=cancel_event,
        on_exception=_on_summary_exception,
        on_timeout=_on_summary_timeout,
    )
    for (_item_index, item), label in zip(indexed_items, labels):
        if label:
            summaries[item.content_id] = label
            continue
        summaries[item.content_id] = _fallback_segment_summary(item.text)
        fallback_count += 1

    if fallback_count:
        logger.warning(
            "get_step_overview segment summaries fell back run_id=%s step=%d count=%d/%d",
            run_id,
            step_id,
            fallback_count,
            len(pending_items),
        )

    return summaries


def _render_get_content_call(step_id: int, item: ContentUnit) -> str:
    return f"`get_content_unit(step_id={step_id}, content_id=\"{item.content_id}\")`"


def _render_edit_content_call(step_id: int, item: ContentUnit) -> str:
    return (
        f"`edit_content(step_id={step_id}, "
        f"content_id=\"{item.content_id}\", instruction=\"...\")`"
    )


def _group_content_units(view) -> list[tuple[str, tuple[str | int, ...], list[ContentUnit]]]:
    groups: list[tuple[str, tuple[str | int, ...], list[ContentUnit]]] = []
    seen: set[tuple[str, tuple[str | int, ...]]] = set()
    for item in view.units:
        key = (item.input_or_output, item.dict_path)
        if key in seen:
            continue
        seen.add(key)
        groups.append((
            item.input_or_output,
            item.dict_path,
            [
                candidate for candidate in view.units
                if candidate.input_or_output == item.input_or_output and candidate.dict_path == item.dict_path
            ],
        ))
    return groups


def _render_content_groups(
    lines: list[str],
    groups: list[tuple[str, tuple[str | int, ...], list[ContentUnit]]],
    item_summaries: dict[str, str],
    *,
    step_id: int,
) -> None:
    if not groups:
        lines.append("(empty)")
        return

    for _input_or_output, dict_path, items in groups:
        lines.append(f"### `{format_dict_path(dict_path)}`")
        for item in items:
            if _should_summarize(item.text):
                rendered_text = item_summaries.get(item.content_id)
                if rendered_text:
                    lines.append(
                        f"- [content_id={item.content_id}] Summarized content ({len(item.text)} chars): {rendered_text}"
                    )
                else:
                    lines.append(
                        f"- [content_id={item.content_id}] Summarized content ({len(item.text)} chars)"
                    )
            else:
                rendered_text = _compact_text(item.text) or "(empty)"
                lines.append(
                    f"- [content_id={item.content_id}] Full content ({len(item.text)} chars): {rendered_text}"
                )
            if _should_summarize(item.text):
                lines.append(f"  Load unsummarized content with {_render_get_content_call(step_id, item)}.")
            lines.append(f"  Edit this content with {_render_edit_content_call(step_id, item)}.")
            lines.append("")
        lines.append("")


def _build_step_content(trace: Trace, index: int, *, cancel_event=None) -> str:
    step_id = index + 1
    semantic_summary = get_cached_step_semantic_summary(trace, step_id)
    record = trace.get(index)
    view = build_step_content_view(record.input_to_show, record.output_to_show)
    content_items = list(view.units)
    logger.info(
        "get_step_overview content items run_id=%s step=%d total=%d summarized=%d",
        trace.run_id or "-",
        step_id,
        len(content_items),
        sum(1 for item in content_items if _should_summarize(item.text)),
    )
    item_summaries = _summarize_content_items(
        trace,
        step_id,
        content_items,
        cancel_event=cancel_event,
    )
    input_groups = [group for group in _group_content_units(view) if group[0] == "input"]
    output_groups = [group for group in _group_content_units(view) if group[0] == "output"]

    lines = [f"# Step {step_id}"]
    if record.name:
        lines.append(f"Name: {record.name}")
    if semantic_summary:
        lines.extend(["", "## Summary", "", semantic_summary])

    lines.extend(["", "## Input Content", ""])
    _render_content_groups(lines, input_groups, item_summaries, step_id=step_id)

    lines.extend(["", "## Output Content", ""])
    _render_content_groups(lines, output_groups, item_summaries, step_id=step_id)

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


def get_or_compute_step_semantic_summary(trace: Trace, step_id: int, *, cancel_event=None) -> str:
    cached_summary = get_cached_step_semantic_summary(trace, step_id)
    if cached_summary is not None:
        return cached_summary

    index, err = resolve_step_index(trace, step_id)
    if err:
        raise ValueError(err)

    record = trace.get(index)
    raise_if_cancelled(cancel_event)

    rendered = render_record_markdown(record, trace.get_diffed(index), view="full")
    structured_summary = build_step_summary(record, rendered_chars=len(rendered))
    semantic_summary = infer_text(
        [{"role": "system", "content": STEP_SUMMARIZE_SYSTEM},
         {"role": "user", "content": structured_summary}],
        tier=_SUMMARY_TIER,
        cancel_event=cancel_event,
        extra_body=_SUMMARY_EXTRA_BODY,
        max_tokens=_STEP_SUMMARY_MAX_TOKENS,
    ).strip()
    logger.info(
        "get_step_overview semantic summary generated run_id=%s step=%d chars=%d",
        trace.run_id or "-",
        step_id,
        len(semantic_summary),
    )
    trace.step_semantic_summary_cache[index] = semantic_summary
    return semantic_summary


def get_step_overview(trace: Trace, step_id=None, cancel_event=None) -> str:
    index, err = resolve_step_index(trace, step_id)
    if err:
        return err
    raise_if_cancelled(cancel_event)

    cached_summary = get_cached_step_semantic_summary(trace, index + 1)
    if index in trace.step_overview_cache:
        cached_result = trace.step_overview_cache[index]
        if not cached_summary or "\n## Summary\n" in cached_result:
            logger.info("get_step_overview cache hit run_id=%s step=%d", trace.run_id or "-", index + 1)
            return cached_result

    result = _build_step_content(trace, index, cancel_event=cancel_event)
    trace.step_overview_cache[index] = result
    return result
