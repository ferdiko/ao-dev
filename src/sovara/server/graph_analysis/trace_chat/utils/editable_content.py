"""Editable content views for trace-chat editing."""

import copy
from dataclasses import dataclass, field
from typing import List, TYPE_CHECKING

from .trace import split_prompt, stringify_field

if TYPE_CHECKING:
    from .trace import Trace


def format_path(path: str) -> str:
    return path or "<root>"


@dataclass
class PathContent:
    """Editable content grouped by visible input/output path."""

    path: str
    paragraphs: List[str]
    codec: str
    branch: str = "input"
    role: str = ""
    shared_prompt_id: str = ""
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


@dataclass
class EditableContentState:
    """Editable content state for one trace step with undo support."""

    paths: List[PathContent]
    undo_stack: List[List[PathContent]] = field(default_factory=list)

    def push_undo(self) -> None:
        self.undo_stack.append(copy.deepcopy(self.paths))

    def pop_undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.paths = self.undo_stack.pop()
        return True


def _block_paragraphs(block) -> List[str]:
    if block.kind == "text":
        return list(block.paragraphs) or [block.text]
    rendered = stringify_field(block.raw_value).strip()
    return split_prompt(rendered) if rendered else [""]


def _blocks_to_path_content(blocks, *, branch: str, prompt_id: str = "") -> List[PathContent]:
    seen_paths = set()
    path_content: List[PathContent] = []
    for block in blocks:
        if block.path in seen_paths:
            continue
        seen_paths.add(block.path)
        path_content.append(PathContent(
            path=block.path,
            paragraphs=_block_paragraphs(block),
            codec=block.codec,
            branch=branch,
            role=block.role,
            shared_prompt_id=prompt_id if branch == "input" else "",
            shared_prompt=bool(branch == "input" and block.is_prompt and prompt_id),
        ))
    return path_content


def build_step_path_content(trace: "Trace", step_index: int) -> List[PathContent]:
    """Expose all visible editable paths for a step."""
    record = trace.records[step_index]
    path_content = _blocks_to_path_content(
        record.input_blocks,
        branch="input",
        prompt_id=record.prompt_key or "",
    )
    path_content.extend(_blocks_to_path_content(record.output_blocks, branch="output"))
    return path_content
