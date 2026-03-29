"""Editable path/paragraph views for trace-chat prompt editing."""

import copy
from dataclasses import dataclass, field
from typing import Dict, List, TYPE_CHECKING

from .trace import split_prompt

if TYPE_CHECKING:
    from .trace import Trace


def format_path(path: str) -> str:
    return path or "<root>"


def format_paragraph_ref(path: str, paragraph: int) -> str:
    return f"{format_path(path)}::p{paragraph}"


@dataclass
class Section:
    """Editable text content for one flattened input path."""

    path: str
    paragraphs: List[str]
    codec: str
    role: str = ""
    prompt_id: str = ""
    shared_prompt: bool = False

    @property
    def display_path(self) -> str:
        return format_path(self.path)

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)

    @text.setter
    def text(self, new_text: str) -> None:
        self.paragraphs = split_prompt(new_text.strip()) if new_text.strip() else [""]

    def preview(self, max_len: int = 80) -> str:
        first = self.paragraphs[0] if self.paragraphs else ""
        first = " ".join(first.split())
        if len(first) <= max_len:
            return first
        return first[: max_len - 3] + "..."

    def paragraph_ref(self, paragraph: int) -> str:
        return format_paragraph_ref(self.path, paragraph)

    def paragraph_refs_summary(self) -> str:
        if not self.paragraphs:
            return ""
        if len(self.paragraphs) == 1:
            return self.paragraph_ref(0)
        return f"{self.paragraph_ref(0)}..{self.paragraph_ref(len(self.paragraphs) - 1)}"


@dataclass
class PromptSections:
    """Editable blocks for one trace step with undo support."""

    prompt_id: str
    sections: List[Section]
    undo_stack: List[List[Section]] = field(default_factory=list)

    def push_undo(self) -> None:
        self.undo_stack.append(copy.deepcopy(self.sections))

    def pop_undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.sections = self.undo_stack.pop()
        return True

    def by_path(self) -> Dict[str, Section]:
        return {section.path: section for section in self.sections}

    def to_table(self) -> str:
        lines = [f"Step [{self.prompt_id}] — {len(self.sections)} editable path(s):"]
        for section in self.sections:
            tags = []
            if section.role:
                tags.append(section.role)
            if section.shared_prompt:
                tags.append("shared prompt")
            tag_str = f" [{' | '.join(tags)}]" if tags else ""
            lines.append(
                f"  `{section.display_path}`{tag_str}  "
                f"{len(section.paragraphs)} paragraph(s)  "
                f"refs: `{section.paragraph_refs_summary()}`  "
                f"\"{section.preview()}\""
            )
        return "\n".join(lines)


def flatten_turn(trace: "Trace", turn_index: int) -> List[Section]:
    """Expose editable text blocks for a step.

    If semantic diffing worked, this returns the step's newly introduced text
    blocks plus a newly introduced shared prompt. If not, it falls back to all
    editable input text blocks for the step.
    """
    diff = trace.diffed[turn_index]
    blocks = [block for block in diff.new_input_blocks if block.editable]

    seen_paths = set()
    sections: List[Section] = []
    for block in blocks:
        if block.path in seen_paths:
            continue
        seen_paths.add(block.path)
        sections.append(Section(
            path=block.path,
            paragraphs=list(block.paragraphs) or [block.text],
            codec=block.codec,
            role=block.role,
            prompt_id=diff.prompt_id or "",
            shared_prompt=bool(block.is_prompt and diff.prompt_id),
        ))

    if sections:
        return sections

    record = trace.records[turn_index]
    fallback_sections: List[Section] = []
    for block in record.input_blocks:
        if not block.editable or block.path in seen_paths:
            continue
        seen_paths.add(block.path)
        fallback_sections.append(Section(
            path=block.path,
            paragraphs=list(block.paragraphs) or [block.text],
            codec=block.codec,
            role=block.role,
            prompt_id=record.prompt_key or "",
            shared_prompt=bool(block.is_prompt and record.prompt_key),
        ))
    return fallback_sections
