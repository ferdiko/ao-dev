"""Shared utilities for parsing and processing agent execution traces.

Trace schema (JSONL, one record per line):
    system_prompt : str       – The system prompt used for this step
    input         : list[dict] – Messages sent to the model (role/content pairs)
    output        : str       – The model's response text
    correct       : bool|None – Whether the output is correct (null = unevaluated)
    label         : str|None  – Classification label (null = unlabeled)
    summary       : str|None  – Human-readable summary (null = unsummarized)
    model/tool    : str|None  – Model ID or tool name that produced the output
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Shared content helpers
# ---------------------------------------------------------------------------

def extract_text_content(content) -> str:
    """Extract text from a message content field.

    Handles plain strings, Anthropic-style content block lists
    ([{"type": "text", "text": "..."}]), and falls back to str().
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, dict):
                parts.append(f"[{block.get('type', 'unknown')} block]")
        return "\n".join(parts)
    return str(content)


def format_messages(messages: list, system_prompt: str = "") -> str:
    """Render a message list into readable text.

    Combines system_prompt (if given) and each message into labeled sections.
    """
    parts = []
    if system_prompt:
        parts.append(f"[system]\n{system_prompt}")
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "unknown")
            content = extract_text_content(msg.get("content", ""))
            parts.append(f"[{role}]\n{content}")
        else:
            parts.append(stringify_field(msg))
    return "\n\n".join(parts)


def stringify_field(value) -> str:
    """Convert a trace field to string. Passes through strings, JSON-dumps everything else."""
    return value if isinstance(value, str) else json.dumps(value)


def extract_tag(raw: str, tag: str, default: str = "") -> str:
    """Extract text between <tag>...</tag> from an LLM response."""
    open_tag = f"<{tag}>"
    close_tag = f"</{tag}>"
    if open_tag in raw and close_tag in raw:
        return raw.split(open_tag)[1].split(close_tag)[0].strip()
    return default


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TraceRecord:
    """A single record in a trace file."""
    system_prompt: str = ""
    input: list = field(default_factory=list)
    output: object = ""  # str or dict (tool call results)
    correct: Optional[bool] = None
    label: Optional[str] = None
    summary: Optional[str] = None
    model_or_tool: Optional[str] = None
    index: int = 0
    node_id: Optional[str] = None  # DB node_id for write-back (set when built from DB)

    def to_dict(self) -> dict:
        return {
            "system_prompt": self.system_prompt,
            "input": self.input,
            "output": self.output,
            "correct": self.correct,
            "label": self.label,
            "summary": self.summary,
            "model/tool": self.model_or_tool,
        }


@dataclass
class DiffedRecord:
    """A trace record showing only what changed relative to prior records.

    For records that continue an existing conversation (same system prompt),
    new_messages contains only the messages appended since the last record
    in that conversation. For the first record in a conversation (or standalone
    records with no system prompt), new_messages equals the full input.
    """
    index: int = 0
    prompt_id: Optional[str] = None
    prompt_is_new: bool = True
    new_messages: list = field(default_factory=list)
    total_messages: int = 0
    output: object = ""
    correct: Optional[bool] = None
    label: Optional[str] = None
    summary: Optional[str] = None
    model_or_tool: Optional[str] = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _prompt_hash(text: str) -> str:
    """Short content hash for a system prompt."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _messages_equal(a: dict, b: dict) -> bool:
    """Compare two message dicts by serialized form."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _compute_new_messages(prev_input: list, cur_input: list) -> Tuple[int, list]:
    """Find the longest shared prefix between two message lists.

    Returns (shared_count, new_messages).
    """
    shared = 0
    for i in range(min(len(prev_input), len(cur_input))):
        if _messages_equal(prev_input[i], cur_input[i]):
            shared += 1
        else:
            break
    return shared, cur_input[shared:]


def parse_record(raw: dict, index: int = 0) -> TraceRecord:
    """Parse a single JSON dict into a TraceRecord."""
    return TraceRecord(
        system_prompt=raw.get("system_prompt") or "",
        input=raw.get("input", []),
        output=raw.get("output", ""),
        correct=raw.get("correct"),
        label=raw.get("label"),
        summary=raw.get("summary"),
        model_or_tool=raw.get("model/tool"),
        index=index,
        node_id=raw.get("node_id"),
    )


def parse_trace(text: str) -> List[TraceRecord]:
    """Parse JSONL trace string into a list of TraceRecords."""
    records = []
    for i, line in enumerate(text.strip().splitlines()):
        line = line.strip()
        if line:
            records.append(parse_record(json.loads(line), index=i))
    return records


def diff_trace(records: List[TraceRecord]) -> Tuple[Dict[str, str], List[DiffedRecord]]:
    """Produce a diffed view of a trace.

    Returns:
        prompt_registry: {prompt_id: full_system_prompt_text}
        diffed_records:  One DiffedRecord per input record with only new messages.

    Conversations are tracked by system_prompt identity. Records with an empty
    system_prompt are treated as standalone.
    """
    prompt_registry: Dict[str, str] = {}
    last_input_by_prompt: Dict[str, list] = {}
    seen_prompt_ids: set = set()
    diffed: List[DiffedRecord] = []

    for rec in records:
        sp = rec.system_prompt

        if sp:
            pid = _prompt_hash(sp)
            if pid not in prompt_registry:
                prompt_registry[pid] = sp
            is_new = pid not in seen_prompt_ids
            seen_prompt_ids.add(pid)
        else:
            pid = None
            is_new = False

        inp = rec.input if isinstance(rec.input, list) else [rec.input]
        if pid is not None and pid in last_input_by_prompt:
            _shared, new_msgs = _compute_new_messages(last_input_by_prompt[pid], inp)
        else:
            new_msgs = inp

        if pid is not None:
            last_input_by_prompt[pid] = inp

        diffed.append(DiffedRecord(
            index=rec.index,
            prompt_id=pid,
            prompt_is_new=is_new,
            new_messages=new_msgs,
            total_messages=len(inp),
            output=rec.output,
            correct=rec.correct,
            label=rec.label,
            summary=rec.summary,
            model_or_tool=rec.model_or_tool,
        ))

    return prompt_registry, diffed


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
    # Caches scoped to this trace instance
    summary_cache: Dict[int, str] = field(default_factory=dict, repr=False)
    verdict_cache: Dict[int, tuple] = field(default_factory=dict, repr=False)
    prompt_sections_cache: Dict[str, Any] = field(default_factory=dict, repr=False)
    session_id: Optional[str] = None  # Set when built from DB; needed for write-back

    @classmethod
    def from_string(cls, raw: str) -> "Trace":
        records = parse_trace(raw)
        prompt_registry, diffed = diff_trace(records)
        return cls(
            raw=raw,
            records=records,
            prompt_registry=prompt_registry,
            diffed=diffed,
        )

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

    def prompt_turns(self) -> Dict[str, List[int]]:
        """Map each prompt_id to the list of turn indices that use it."""
        groups: Dict[str, List[int]] = {}
        for dr in self.diffed:
            if dr.prompt_id is not None:
                groups.setdefault(dr.prompt_id, []).append(dr.index)
        return groups
