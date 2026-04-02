"""Shared utilities for parsing and processing agent execution traces.

Trace chat now treats `to_show` as the source of truth and renders it into a
generic, path-based markdown view. Best-effort semantic hints such as
system-prompt and message detection are derived only to improve prompt
construction and diffing; they are not authoritative parsing.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .content_utils import extract_text_content, is_text_block_list, split_prompt, stringify_field

_PROMPT_KEYS = {"system", "instructions", "prompt"}


def extract_tag(raw: str, tag: str, default: str = "") -> str:
    """Extract text between <tag>...</tag> from an LLM response."""
    open_tag = f"<{tag}>"
    close_tag = f"</{tag}>"
    if open_tag in raw and close_tag in raw:
        return raw.split(open_tag)[1].split(close_tag)[0].strip()
    return default


def _prompt_hash(text: str) -> str:
    """Short content hash for a detected shared prompt."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _path_join(prefix: str, part: str | int) -> str:
    part_str = str(part)
    return f"{prefix}.{part_str}" if prefix else part_str


def _is_small_json_blob(value: Any) -> bool:
    if not isinstance(value, (dict, list)):
        return False
    try:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True)) <= 160
    except TypeError:
        return False


def _summarize_paragraph(paragraph: str) -> str:
    stripped = " ".join(paragraph.split())
    if len(stripped) <= 80:
        return ""
    sentence = stripped.split(". ")[0].strip()
    if not sentence:
        sentence = stripped
    if len(sentence) > 120:
        sentence = sentence[:117].rstrip() + "..."
    return sentence


# ---------------------------------------------------------------------------
# Render models
# ---------------------------------------------------------------------------

@dataclass
class RenderBlock:
    branch: str
    path: str
    kind: str
    raw_value: Any
    codec: str
    editable: bool = False
    paragraphs: List[str] = field(default_factory=list)
    paragraph_summaries: List[str] = field(default_factory=list)
    role: str = ""
    message_position: Optional[int] = None
    is_prompt: bool = False

    @property
    def text(self) -> str:
        if self.paragraphs:
            return "\n\n".join(self.paragraphs)
        return extract_text_content(self.raw_value)


def block_char_count(block: RenderBlock) -> int:
    """Count the user-visible chars represented by one render block."""
    if block.kind == "text":
        return len(block.text)
    return len(stringify_field(block.raw_value))


def blocks_char_count(blocks: List[RenderBlock]) -> int:
    """Count the user-visible chars represented by multiple render blocks."""
    return sum(block_char_count(block) for block in blocks)


@dataclass
class TraceRecord:
    """A single record in a trace."""

    system_prompt: str = ""
    input: list = field(default_factory=list)
    output: object = ""
    correct: Optional[bool] = None
    label: Optional[str] = None
    summary: Optional[str] = None
    name: Optional[str] = None
    index: int = 0
    node_uuid: Optional[str] = None
    input_to_show: dict = field(default_factory=dict)
    output_to_show: dict = field(default_factory=dict)
    input_blocks: List[RenderBlock] = field(default_factory=list)
    output_blocks: List[RenderBlock] = field(default_factory=list)
    prompt_path: Optional[str] = None
    prompt_codec: Optional[str] = None
    message_list_path: Optional[str] = None
    prompt_key: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "system_prompt": self.system_prompt,
            "input": self.input,
            "output": self.output,
            "correct": self.correct,
            "label": self.label,
            "summary": self.summary,
            "name": self.name,
        }


@dataclass
class DiffedRecord:
    """A trace record showing only what changed relative to prior records."""

    index: int = 0
    prompt_id: Optional[str] = None
    prompt_is_new: bool = True
    new_messages: list = field(default_factory=list)
    total_messages: int = 0
    output: object = ""
    correct: Optional[bool] = None
    label: Optional[str] = None
    summary: Optional[str] = None
    name: Optional[str] = None
    new_input_blocks: List[RenderBlock] = field(default_factory=list)


@dataclass
class _SemanticHints:
    system_prompt: str = ""
    prompt_path: Optional[str] = None
    prompt_codec: Optional[str] = None
    message_list_path: Optional[str] = None
    input_messages: list = field(default_factory=list)
    message_positions: Dict[str, Tuple[int, str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Best-effort semantic hints for prompt construction
# ---------------------------------------------------------------------------

def _collect_text_candidates(value: Any, path: str = "") -> list[tuple[str, Any, str]]:
    candidates: list[tuple[str, Any, str]] = []
    if isinstance(value, str):
        candidates.append((path, value, "plain_text"))
        return candidates
    if is_text_block_list(value):
        candidates.append((path, value, "text_block_list"))
        return candidates
    if isinstance(value, dict):
        for key, child in value.items():
            candidates.extend(_collect_text_candidates(child, _path_join(path, key)))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            candidates.extend(_collect_text_candidates(child, _path_join(path, idx)))
    return candidates


def _find_message_list(value: Any, path: str = "") -> Optional[tuple[str, list]]:
    # Heuristic only for prompt construction and convenience rendering.
    # Do not use this as authoritative parsing or exact persistence logic.
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        if all("role" in item and "content" in item for item in value):
            return path, value
    if isinstance(value, dict):
        for key, child in value.items():
            found = _find_message_list(child, _path_join(path, key))
            if found:
                return found
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            found = _find_message_list(child, _path_join(path, idx))
            if found:
                return found
    return None


def _build_semantic_hints(to_show: dict) -> _SemanticHints:
    # Heuristic only for prompt construction and diff readability.
    # Write-back always uses stored paths/codecs, never these guesses.
    hints = _SemanticHints()

    message_candidate = _find_message_list(to_show)
    raw_messages: list[dict] = []
    if message_candidate:
        message_list_path, raw_messages = message_candidate
        hints.message_list_path = message_list_path

    prompt_candidates = []
    for candidate_path, raw_value, codec in _collect_text_candidates(to_show):
        terminal = candidate_path.rsplit(".", 1)[-1]
        if terminal not in _PROMPT_KEYS:
            continue
        if hints.message_list_path and candidate_path.startswith(f"{hints.message_list_path}."):
            continue
        prompt_candidates.append((candidate_path, raw_value, codec))

    if prompt_candidates:
        prompt_path, raw_prompt, prompt_codec = prompt_candidates[0]
        hints.system_prompt = extract_text_content(raw_prompt)
        hints.prompt_path = prompt_path
        hints.prompt_codec = prompt_codec

    filtered_messages = []
    semantic_index = 0
    for raw_index, message in enumerate(raw_messages):
        role = str(message.get("role", "unknown"))
        content = message.get("content", "")
        content_path = _path_join(_path_join(hints.message_list_path or "", raw_index), "content")
        content_codec = "text_block_list" if is_text_block_list(content) else "plain_text"
        if not hints.system_prompt and role == "system":
            hints.system_prompt = extract_text_content(content)
            hints.prompt_path = content_path
            hints.prompt_codec = content_codec
            continue

        filtered_messages.append(message)
        item_prefix = _path_join(hints.message_list_path or "", raw_index)
        hints.message_positions[item_prefix] = (semantic_index, role)
        semantic_index += 1

    hints.input_messages = filtered_messages
    return hints


# ---------------------------------------------------------------------------
# Rendering and parsing
# ---------------------------------------------------------------------------

def _find_message_meta(path: str, semantic_hints: _SemanticHints) -> tuple[Optional[int], str]:
    for prefix, (position, role) in semantic_hints.message_positions.items():
        if path == prefix or path.startswith(f"{prefix}."):
            return position, role
    return None, ""


def _should_expand_container(path: str, semantic_hints: _SemanticHints) -> bool:
    if not path:
        return True

    important_paths = [semantic_hints.prompt_path, semantic_hints.message_list_path]
    important_paths.extend(semantic_hints.message_positions.keys())
    return any(
        important and (important == path or important.startswith(f"{path}."))
        for important in important_paths
    )


def _render_blocks(
    value: Any,
    branch: str,
    *,
    path: str = "",
    semantic_hints: Optional[_SemanticHints] = None,
) -> List[RenderBlock]:
    semantic_hints = semantic_hints or _SemanticHints()
    message_position, role = _find_message_meta(path, semantic_hints)

    if isinstance(value, str):
        paragraphs = split_prompt(value)
        summaries = [_summarize_paragraph(paragraph) for paragraph in paragraphs]
        terminal = path.rsplit(".", 1)[-1] if path else ""
        return [RenderBlock(
            branch=branch,
            path=path,
            kind="text",
            raw_value=value,
            codec="plain_text",
            editable=(branch == "input" and terminal not in {"role", "type"}),
            paragraphs=paragraphs,
            paragraph_summaries=summaries,
            role=role,
            message_position=message_position,
            is_prompt=(path == semantic_hints.prompt_path),
        )]

    if is_text_block_list(value):
        text = extract_text_content(value)
        paragraphs = split_prompt(text)
        summaries = [_summarize_paragraph(paragraph) for paragraph in paragraphs]
        return [RenderBlock(
            branch=branch,
            path=path,
            kind="text",
            raw_value=value,
            codec="text_block_list",
            editable=(branch == "input"),
            paragraphs=paragraphs,
            paragraph_summaries=summaries,
            role=role,
            message_position=message_position,
            is_prompt=(path == semantic_hints.prompt_path),
        )]

    if isinstance(value, (int, float, bool)) or value is None:
        return [RenderBlock(
            branch=branch,
            path=path,
            kind="scalar",
            raw_value=value,
            codec="scalar",
            role=role,
            message_position=message_position,
            is_prompt=(path == semantic_hints.prompt_path),
        )]

    if (
        path
        and isinstance(value, (dict, list))
        and path != semantic_hints.message_list_path
        and message_position is None
        and not _should_expand_container(path, semantic_hints)
        and _is_small_json_blob(value)
    ):
        return [RenderBlock(
            branch=branch,
            path=path,
            kind="json_blob",
            raw_value=value,
            codec="json_value",
            role=role,
            message_position=message_position,
            is_prompt=(path == semantic_hints.prompt_path),
        )]

    blocks: List[RenderBlock] = []
    if isinstance(value, dict):
        for key, child in value.items():
            blocks.extend(_render_blocks(
                child,
                branch,
                path=_path_join(path, key),
                semantic_hints=semantic_hints,
            ))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            blocks.extend(_render_blocks(
                child,
                branch,
                path=_path_join(path, idx),
                semantic_hints=semantic_hints,
            ))
    else:
        blocks.append(RenderBlock(
            branch=branch,
            path=path,
            kind="scalar",
            raw_value=str(value),
            codec="scalar",
            role=role,
            message_position=message_position,
            is_prompt=(path == semantic_hints.prompt_path),
        ))
    return blocks


def _choose_output_value(output_to_show: dict, output_blocks: List[RenderBlock]) -> object:
    text_blocks = [block for block in output_blocks if block.kind == "text"]
    if len(text_blocks) == 1 and text_blocks[0].path:
        return text_blocks[0].text
    return output_to_show


def build_trace_record_from_to_show(
    input_to_show: dict,
    output_to_show: dict,
    *,
    index: int = 0,
    correct: Optional[bool] = None,
    label: Optional[str] = None,
    summary: Optional[str] = None,
    name: Optional[str] = None,
    node_uuid: Optional[str] = None,
) -> TraceRecord:
    semantic_hints = _build_semantic_hints(input_to_show)
    input_blocks = _render_blocks(input_to_show, "input", semantic_hints=semantic_hints)
    output_blocks = _render_blocks(output_to_show, "output")

    prompt_key = _prompt_hash(semantic_hints.system_prompt) if semantic_hints.system_prompt else None

    return TraceRecord(
        system_prompt=semantic_hints.system_prompt,
        input=semantic_hints.input_messages,
        output=_choose_output_value(output_to_show, output_blocks),
        correct=correct,
        label=label,
        summary=summary,
        name=name or "",
        index=index,
        node_uuid=node_uuid,
        input_to_show=input_to_show or {},
        output_to_show=output_to_show or {},
        input_blocks=input_blocks,
        output_blocks=output_blocks,
        prompt_path=semantic_hints.prompt_path,
        prompt_codec=semantic_hints.prompt_codec,
        message_list_path=semantic_hints.message_list_path,
        prompt_key=prompt_key,
    )


def parse_record(raw: dict, index: int = 0) -> TraceRecord:
    """Parse a single JSON dict into a TraceRecord."""
    if "input_to_show" in raw or "output_to_show" in raw:
        return build_trace_record_from_to_show(
            raw.get("input_to_show") or {},
            raw.get("output_to_show") or {},
            index=index,
            correct=raw.get("correct"),
            label=raw.get("label"),
            summary=raw.get("summary"),
            name=raw.get("name") or "",
            node_uuid=raw.get("node_uuid"),
        )

    input_to_show = {}
    system_prompt = raw.get("system_prompt") or ""
    input_messages = raw.get("input", [])
    if system_prompt:
        input_to_show["system_prompt"] = system_prompt
    if input_messages:
        input_to_show["messages"] = input_messages
    output_to_show = {"output": raw.get("output", "")}

    record = build_trace_record_from_to_show(
        input_to_show,
        output_to_show,
        index=index,
        correct=raw.get("correct"),
        label=raw.get("label"),
        summary=raw.get("summary"),
        name=raw.get("name") or "",
        node_uuid=raw.get("node_uuid"),
    )
    if system_prompt:
        record.system_prompt = system_prompt
        record.prompt_path = "system_prompt"
        record.prompt_codec = "plain_text"
        record.prompt_key = _prompt_hash(system_prompt)
        for block in record.input_blocks:
            if block.path == "system_prompt":
                block.is_prompt = True
    if input_messages:
        record.input = input_messages if isinstance(input_messages, list) else [input_messages]
        record.message_list_path = "messages"
    record.output = raw.get("output", "")
    return record


def parse_trace(text: str) -> List[TraceRecord]:
    """Parse JSONL trace string into a list of TraceRecords."""
    records = []
    for i, line in enumerate(text.strip().splitlines()):
        line = line.strip()
        if line:
            records.append(parse_record(json.loads(line), index=i))
    return records


def _messages_equal(a: dict, b: dict) -> bool:
    """Compare two messages structurally."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _compute_new_messages(prev_input: list, cur_input: list) -> Tuple[int, list]:
    """Find the longest shared prefix between two message lists."""
    shared = 0
    for i in range(min(len(prev_input), len(cur_input))):
        if _messages_equal(prev_input[i], cur_input[i]):
            shared += 1
        else:
            break
    return shared, cur_input[shared:]


def diff_trace(records: List[TraceRecord]) -> Tuple[Dict[str, str], List[DiffedRecord]]:
    """Produce a diffed view of a trace."""
    prompt_registry: Dict[str, str] = {}
    last_input_by_prompt: Dict[str, list] = {}
    seen_prompt_ids: set = set()
    diffed: List[DiffedRecord] = []

    for rec in records:
        pid = rec.prompt_key
        if pid:
            prompt_registry.setdefault(pid, rec.system_prompt)
            is_new = pid not in seen_prompt_ids
            seen_prompt_ids.add(pid)
        else:
            is_new = False

        semantic_messages = rec.input if isinstance(rec.input, list) else []
        if pid and semantic_messages and pid in last_input_by_prompt:
            shared, new_messages = _compute_new_messages(last_input_by_prompt[pid], semantic_messages)
        else:
            shared, new_messages = 0, semantic_messages

        if pid and semantic_messages:
            last_input_by_prompt[pid] = semantic_messages

        new_input_blocks = []
        for block in rec.input_blocks:
            if block.is_prompt:
                if is_new:
                    new_input_blocks.append(block)
                continue
            if block.message_position is not None:
                if block.message_position >= shared:
                    new_input_blocks.append(block)
                continue
            new_input_blocks.append(block)

        diffed.append(DiffedRecord(
            index=rec.index,
            prompt_id=pid,
            prompt_is_new=is_new,
            new_messages=new_messages,
            total_messages=len(semantic_messages),
            output=rec.output,
            correct=rec.correct,
            label=rec.label,
            summary=rec.summary,
            name=rec.name,
            new_input_blocks=new_input_blocks,
        ))

    return prompt_registry, diffed


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _render_text_block(block: RenderBlock) -> List[str]:
    display_path = block.path or "<root>"
    lines: List[str] = [f"### `{display_path}`"]
    if block.role and not display_path.endswith(".role"):
        lines.append(f"Role: `{block.role}`")

    text = block.text
    if len(text) <= 160 and len(block.paragraphs) == 1:
        lines.append(text or "(empty)")
        return lines

    for idx, paragraph in enumerate(block.paragraphs, start=1):
        lines.append(f"Paragraph {idx}:")
        lines.append(paragraph or "(empty)")
        summary = block.paragraph_summaries[idx - 1] if idx - 1 < len(block.paragraph_summaries) else ""
        if summary:
            lines.append("Summary:")
            lines.append(summary)
    return lines


def render_blocks_markdown(blocks: List[RenderBlock]) -> str:
    rendered: List[str] = []
    for block in blocks:
        if block.kind == "text":
            rendered.extend(_render_text_block(block))
        elif block.kind == "scalar":
            rendered.append(f"### `{block.path or '<root>'}`")
            rendered.append(f"`{json.dumps(block.raw_value, ensure_ascii=False)}`")
        else:
            rendered.append(f"### `{block.path or '<root>'}`")
            rendered.append("```json")
            rendered.append(stringify_field(block.raw_value))
            rendered.append("```")
        rendered.append("")
    return "\n".join(rendered).strip()


def render_record_markdown(record: TraceRecord, diffed: Optional[DiffedRecord] = None, *, view: str = "full") -> str:
    lines = [f"# Step {record.index + 1}"]
    if record.name:
        lines.append(f"Name: {record.name}")

    if view == "output":
        output_blocks = record.output_blocks
        if output_blocks:
            lines.extend(["", "## Output", "", render_blocks_markdown(output_blocks)])
        else:
            lines.extend(["", "## Output", "", "(empty)"])
        return "\n".join(lines).strip()

    if view == "diff" and diffed is not None:
        lines.append("")
        lines.append("## Input")
        if diffed.prompt_id and not diffed.prompt_is_new:
            lines.append("")
            lines.append(f"Prompt `{diffed.prompt_id}` is reused from an earlier step.")
        lines.append("")
        if diffed.new_input_blocks:
            lines.append(render_blocks_markdown(diffed.new_input_blocks))
        else:
            lines.append("(no new input content detected)")
    else:
        lines.append("")
        lines.append("## Input")
        lines.append("")
        if record.input_blocks:
            lines.append(render_blocks_markdown(record.input_blocks))
        else:
            lines.append("(empty)")

    lines.extend(["", "## Output", ""])
    if record.output_blocks:
        lines.append(render_blocks_markdown(record.output_blocks))
    else:
        lines.append("(empty)")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Trace — the top-level object passed to tools
# ---------------------------------------------------------------------------

@dataclass
class Trace:
    """Parsed trace with precomputed diff views and per-trace caches."""

    raw: str
    records: List[TraceRecord]
    prompt_registry: Dict[str, str] = field(default_factory=dict)
    diffed: List[DiffedRecord] = field(default_factory=list)
    summary_cache: Dict[int, str] = field(default_factory=dict, repr=False)
    step_overview_cache: Dict[int, str] = field(default_factory=dict, repr=False)
    step_semantic_summary_cache: Dict[int, str] = field(default_factory=dict, repr=False)
    verdict_cache: Dict[int, tuple] = field(default_factory=dict, repr=False)
    edit_undo_stack: Dict[int, List[tuple[dict, dict]]] = field(default_factory=dict, repr=False)
    prefetched_summary: str = field(default="", repr=False)
    run_id: Optional[str] = None

    @classmethod
    def from_string(cls, raw: str) -> "Trace":
        records = parse_trace(raw)
        prompt_registry, diffed = diff_trace(records)
        return cls(raw=raw, records=records, prompt_registry=prompt_registry, diffed=diffed)

    @classmethod
    def from_records(cls, records: List[TraceRecord], raw: str = "") -> "Trace":
        prompt_registry, diffed = diff_trace(records)
        return cls(raw=raw, records=records, prompt_registry=prompt_registry, diffed=diffed)

    def __len__(self) -> int:
        return len(self.records)

    def get(self, index: int) -> TraceRecord:
        if index < 0 or index >= len(self.records):
            raise IndexError(f"Step {index + 1} out of range (1–{len(self.records)})")
        return self.records[index]

    def get_diffed(self, index: int) -> DiffedRecord:
        if index < 0 or index >= len(self.diffed):
            raise IndexError(f"Step {index + 1} out of range (1–{len(self.diffed)})")
        return self.diffed[index]

    def refresh_after_edit(
        self,
        affected_indices: set[int],
        *,
        keep_editable_content_for: Optional[int] = None,
    ) -> None:
        """Invalidate derived analysis and recompute structural views after an edit."""
        for idx in affected_indices:
            if 0 <= idx < len(self.records):
                self.records[idx].summary = None
                self.records[idx].correct = None

        self.summary_cache.clear()
        self.step_overview_cache.clear()
        self.step_semantic_summary_cache.clear()
        self.verdict_cache.clear()
        self.prefetched_summary = ""

        self.prompt_registry, self.diffed = diff_trace(self.records)

    def prompt_turns(self) -> Dict[str, List[int]]:
        groups: Dict[str, List[int]] = {}
        for dr in self.diffed:
            if dr.prompt_id is not None:
                groups.setdefault(dr.prompt_id, []).append(dr.index)
        return groups
