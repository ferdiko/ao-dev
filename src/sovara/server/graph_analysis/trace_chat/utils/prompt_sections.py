"""Prompt sectioning, labeling, and undo support for editing."""

import copy
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, TYPE_CHECKING

from .llm_backend import infer_text
from .trace import extract_text_content

if TYPE_CHECKING:
    from .trace import Trace

LABEL_SYSTEM = (
    "Label this text section in exactly 4-5 words. "
    "Return only the label, nothing else."
)

_HEADING_RE = re.compile(r"^#{1,6}\s+\S")


@dataclass
class Section:
    """A single section of a prompt or message."""
    text: str
    label: str = ""
    msg_index: int = -1  # -1 = system prompt, 0+ = index in new_messages
    role: str = ""        # "system", "user", "assistant", etc.


def split_prompt(text: str) -> List[Section]:
    """Split a prompt into sections on double newlines, merging orphan headings."""
    chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
    if not chunks:
        return [Section(text="")]

    merged: List[Section] = []
    i = 0
    while i < len(chunks):
        lines = chunks[i].splitlines()
        is_heading_only = len(lines) == 1 and bool(_HEADING_RE.match(lines[0]))
        if is_heading_only and i + 1 < len(chunks):
            # Don't merge if the next chunk is also a heading-only line —
            # keep this heading standalone and let the next iteration handle it.
            next_lines = chunks[i + 1].splitlines()
            next_is_heading = len(next_lines) == 1 and bool(_HEADING_RE.match(next_lines[0]))
            if not next_is_heading:
                merged.append(Section(text=chunks[i] + "\n\n" + chunks[i + 1]))
                i += 2
                continue
        merged.append(Section(text=chunks[i]))
        i += 1

    return merged


def label_sections(sections: List[Section], model: str) -> None:
    """Generate 4-5 word labels for each section via parallel LLM calls."""
    def _label_one(section: Section) -> None:
        text = section.text[:2000]
        result = infer_text(
            [{"role": "user", "content": text}],
            model=model,
            system=LABEL_SYSTEM,
            tier="cheap",
            max_tokens=32,
        )
        section.label = result.strip() or "(unlabeled)"

    with ThreadPoolExecutor() as pool:
        list(pool.map(_label_one, sections))


@dataclass
class PromptSections:
    """Manages sectioned view of a prompt with undo support."""
    prompt_id: str
    sections: List[Section]
    labeled: bool = False
    undo_stack: List[List[Section]] = field(default_factory=list)

    def push_undo(self) -> None:
        """Snapshot current sections before a mutation."""
        self.undo_stack.append(copy.deepcopy(self.sections))

    def pop_undo(self) -> bool:
        """Revert to the previous snapshot. Returns False if nothing to undo."""
        if not self.undo_stack:
            return False
        self.sections = self.undo_stack.pop()
        return True

    def reassemble(self, registry: Dict[str, str]) -> None:
        """Write the current sections back to the prompt registry."""
        registry[self.prompt_id] = "\n\n".join(s.text for s in self.sections)

    def to_table(self) -> str:
        """Format sections as an index + label + preview table."""
        lines = [f"Turn [{self.prompt_id}] — {len(self.sections)} sections:"]
        for i, s in enumerate(self.sections):
            first_line = s.text.split("\n")[0]
            preview = first_line[:60] + ("..." if len(first_line) > 60 else "")
            role_tag = f"[{s.role}]  " if s.role else ""
            lines.append(f"  {i:>2}  {role_tag}{s.label:<28s}  \"{preview}\"")
        return "\n".join(lines)


def flatten_turn(trace: "Trace", turn_index: int, model: str) -> List[Section]:
    """Flatten a turn's new content (system prompt + new messages) into sections."""
    diff = trace.diffed[turn_index]
    record = trace.records[turn_index]
    sections: List[Section] = []

    # System prompt sections (only if first introduced in this turn)
    if diff.prompt_is_new and record.system_prompt:
        for s in split_prompt(record.system_prompt):
            s.msg_index = -1
            s.role = "system"
            sections.append(s)

    # New message sections
    for i, msg in enumerate(diff.new_messages):
        text = extract_text_content(msg.get("content", ""))
        role = msg.get("role", "unknown")
        if not text.strip():
            continue
        for s in split_prompt(text):
            s.msg_index = i
            s.role = role
            sections.append(s)

    label_sections(sections, model)
    return sections
