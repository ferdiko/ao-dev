"""Step-global content item helpers for trace-chat tools."""

from dataclasses import dataclass
from typing import Optional, Sequence

INLINE_CONTENT_CHAR_LIMIT = 80


@dataclass(frozen=True)
class StepContentItem:
    content_id: str
    branch: str
    path: str
    display_path: str
    codec: str
    text: str
    summarized: bool
    paragraph_index: Optional[int] = None


def _next_content_id(items: list[StepContentItem]) -> str:
    return f"c{len(items)}"


def _should_summarize(text: str) -> bool:
    return len(text) >= INLINE_CONTENT_CHAR_LIMIT


def build_step_content_items(sections: Sequence) -> list[StepContentItem]:
    """Enumerate all visible input/output content units for one step."""
    items: list[StepContentItem] = []

    for section in sections:
        paragraphs = list(section.paragraphs) or [section.text]
        for paragraph_index, text in enumerate(paragraphs):
            items.append(StepContentItem(
                content_id=_next_content_id(items),
                branch=section.branch,
                path=section.path,
                display_path=section.display_path,
                codec=section.codec,
                text=text,
                summarized=_should_summarize(text),
                paragraph_index=paragraph_index,
            ))

    return items
