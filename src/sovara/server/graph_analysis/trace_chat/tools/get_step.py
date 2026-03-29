"""get_step tool — returns content for a specific step with view options."""

from ..logger import format_log_tags, get_logger
from ..utils.prompt_sections import format_paragraph_ref, format_path
from ..utils.step_ids import resolve_step_index
from ..utils.trace import Trace, blocks_char_count, render_record_markdown, stringify_field

logger = get_logger()
MAX_FULL_STEP_CHARS = 5000
MAX_PREVIEW_PARAGRAPHS_PER_BLOCK = 4


def should_withhold_raw_view(rendered_chars: int) -> bool:
    return rendered_chars > MAX_FULL_STEP_CHARS


def _preview_text(text: str, max_len: int = 120) -> str:
    compact = " ".join(text.split()).strip()
    if not compact:
        return "(empty)"
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


def _render_block_preview(block, *, include_refs: bool) -> list[str]:
    display_path = format_path(block.path)
    lines = [f"### `{display_path}`"]
    if block.role and not display_path.endswith(".role"):
        lines.append(f"Role: `{block.role}`")

    if block.kind != "text":
        lines.append(f"{block.kind} block, {len(stringify_field(block.raw_value))} chars")
        return lines

    char_count = len(block.text)
    lines.append(f"{len(block.paragraphs)} paragraph(s), {char_count} chars")

    if include_refs and block.path and block.paragraphs:
        if len(block.paragraphs) == 1:
            refs = format_paragraph_ref(block.path, 0)
        else:
            refs = (
                f"{format_paragraph_ref(block.path, 0)}.."
                f"{format_paragraph_ref(block.path, len(block.paragraphs) - 1)}"
            )
        lines.append(f"Refs: `{refs}`")

    for idx, paragraph in enumerate(block.paragraphs[:MAX_PREVIEW_PARAGRAPHS_PER_BLOCK]):
        summary = block.paragraph_summaries[idx] if idx < len(block.paragraph_summaries) else ""
        lines.append(f"- p{idx}: {summary or _preview_text(paragraph)}")

    remaining = len(block.paragraphs) - MAX_PREVIEW_PARAGRAPHS_PER_BLOCK
    if remaining > 0:
        lines.append(f"- ... {remaining} more paragraph(s)")

    return lines


def _partition_input_blocks(record) -> tuple[list, list]:
    text_blocks = []
    other_blocks = []
    for block in record.input_blocks:
        if block.kind == "text":
            text_blocks.append(block)
        else:
            other_blocks.append(block)
    return text_blocks, other_blocks


def build_step_summary(
    record,
    *,
    rendered_chars: int | None = None,
) -> str:
    lines = [f"# Step {record.index + 1}"]
    if record.name:
        lines.append(f"Name: {record.name}")
    if rendered_chars is not None:
        lines.append(f"Full raw size: {rendered_chars} chars")
    if record.summary:
        lines.extend(["", "Recorded summary:", record.summary])

    text_blocks, other_input_blocks = _partition_input_blocks(record)

    lines.extend(["", "## Input Text Sections", ""])
    if text_blocks:
        for block in text_blocks:
            lines.extend(_render_block_preview(block, include_refs=block.editable))
            lines.append("")
    else:
        lines.append("(none)")

    lines.extend(["", "## Other Input Fields", ""])
    if other_input_blocks:
        for block in other_input_blocks:
            lines.extend(_render_block_preview(block, include_refs=False))
            lines.append("")
    else:
        lines.append("(none)")

    lines.extend(["", "## Output Summary", ""])
    if record.output_blocks:
        for block in record.output_blocks:
            lines.extend(_render_block_preview(block, include_refs=False))
            lines.append("")
    else:
        lines.append("(empty)")

    return "\n".join(lines).strip()


def get_step(trace: Trace, step_id, view="full") -> str:
    index, err = resolve_step_index(trace, step_id)
    if err:
        return err

    if view not in ("full", "diff", "output"):
        return f"Error: view must be 'full', 'diff', or 'output', got '{view}'."

    record = trace.get(index)
    diffed = trace.get_diffed(index)
    rendered = render_record_markdown(record, diffed, view=view)
    log_tag = format_log_tags(
        "trace_tool",
        run_id=trace.run_id or "-",
        tool="get_step",
        step=index + 1,
        view=view,
    )

    if should_withhold_raw_view(len(rendered)):
        logger.info(
            "%s raw view withheld chars=%d limit=%d",
            log_tag,
            len(rendered),
            MAX_FULL_STEP_CHARS,
        )
        from .get_step_overview import get_step_overview

        overview = get_step_overview(trace, step_id=index + 1)
        input_chars = blocks_char_count(record.input_blocks)
        output_chars = blocks_char_count(record.output_blocks)
        return "\n".join([
            (
                f"Step {index + 1} is too long to load inline in requested `{view}` view "
                f"({input_chars} input chars, {output_chars} output chars)."
            ),
            "",
            "Showing `get_step_overview` instead:",
            "",
            overview,
            "",
            "Inspect specific parts with:",
            f"- `get_content(step_id={index + 1}, path=\"...\", content_id=\"...\")` for one input content unit from the overview",
            f"- `get_step(step_id={index + 1}, view=\"diff\")` for only the new raw input content in this step",
            f"- `get_step(step_id={index + 1}, view=\"output\")` for the raw output only",
            f"- `ask_step(step_id={index + 1}, question=\"...\")` for a targeted question about the step",
        ])

    return rendered
