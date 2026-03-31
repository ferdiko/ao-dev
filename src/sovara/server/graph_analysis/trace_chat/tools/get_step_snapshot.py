"""get_step_snapshot tool — returns raw content for one step."""

from ..logger import format_log_tags, get_logger
from ..utils.editable_content import format_path
from ..utils.step_ids import resolve_step_index
from ..utils.trace import Trace, blocks_char_count, stringify_field

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


def render_block_preview(block) -> list[str]:
    display_path = format_path(block.path)
    lines = [f"### `{display_path}`"]
    if block.role and not display_path.endswith(".role"):
        lines.append(f"Role: `{block.role}`")

    if block.kind != "text":
        lines.append(f"{block.kind} block, {len(stringify_field(block.raw_value))} chars")
        return lines

    char_count = len(block.text)
    lines.append(f"{len(block.paragraphs)} paragraph(s), {char_count} chars")

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
            lines.extend(render_block_preview(block))
            lines.append("")
    else:
        lines.append("(none)")

    lines.extend(["", "## Other Input Fields", ""])
    if other_input_blocks:
        for block in other_input_blocks:
            lines.extend(render_block_preview(block))
            lines.append("")
    else:
        lines.append("(none)")

    lines.extend(["", "## Output Summary", ""])
    if record.output_blocks:
        for block in record.output_blocks:
            lines.extend(render_block_preview(block))
            lines.append("")
    else:
        lines.append("(empty)")

    return "\n".join(lines).strip()


def _render_raw_block(block) -> list[str]:
    lines = [f"### `{format_path(block.path)}`"]

    if isinstance(block.raw_value, str):
        lines.append(block.raw_value)
        return lines

    if block.kind == "scalar":
        lines.append(f"`{stringify_field(block.raw_value)}`")
        return lines

    lines.append("```json")
    lines.append(stringify_field(block.raw_value))
    lines.append("```")
    return lines


def _render_raw_blocks(blocks: list) -> str:
    rendered: list[str] = []
    for block in blocks:
        rendered.extend(_render_raw_block(block))
        rendered.append("")
    return "\n".join(rendered).strip()


def _render_record_raw(record, diffed=None, *, scope: str = "full") -> str:
    lines = [f"# Step {record.index + 1}"]
    if record.name:
        lines.append(f"Name: {record.name}")

    if scope == "new_input" and diffed is not None:
        lines.extend(["", "## Input"])
        if diffed.prompt_id and not diffed.prompt_is_new:
            lines.extend(["", f"Prompt `{diffed.prompt_id}` is reused from an earlier step."])
        lines.append("")
        if diffed.new_input_blocks:
            lines.append(_render_raw_blocks(diffed.new_input_blocks))
        else:
            lines.append("(no new input content detected)")
    else:
        lines.extend(["", "## Input", ""])
        if record.input_blocks:
            lines.append(_render_raw_blocks(record.input_blocks))
        else:
            lines.append("(empty)")

    lines.extend(["", "## Output", ""])
    if record.output_blocks:
        lines.append(_render_raw_blocks(record.output_blocks))
    else:
        lines.append("(empty)")
    return "\n".join(lines).strip()


def get_step_snapshot(trace: Trace, step_id, scope="full") -> str:
    index, err = resolve_step_index(trace, step_id)
    if err:
        return err

    if scope not in ("full", "new_input"):
        return f"Error: scope must be 'full' or 'new_input', got '{scope}'."

    record = trace.get(index)
    diffed = trace.get_diffed(index)
    rendered = _render_record_raw(record, diffed, scope=scope)
    log_tag = format_log_tags(
        "trace_tool",
        run_id=trace.run_id or "-",
        tool="get_step_snapshot",
        step=index + 1,
        snapshot_scope=scope,
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
                f"Step {index + 1} is too long to load inline in requested `{scope}` scope "
                f"({input_chars} input chars, {output_chars} output chars)."
            ),
            "",
            "Showing `get_step_overview` instead:",
            "",
            overview,
            "",
            "Inspect specific parts with:",
            f"- `get_content_unit(step_id={index + 1}, content_id=\"c0\")` for one content unit from the overview",
            f"- `get_step_snapshot(step_id={index + 1}, scope=\"new_input\")` for the new raw input plus full output in this step",
            f"- `ask_step(step_id={index + 1}, question=\"...\")` for a targeted question about the step",
        ])

    return rendered
