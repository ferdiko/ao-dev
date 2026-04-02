"""Shared text/content helpers for trace-chat."""

import json
import re
from typing import Any

_HEADING_RE = re.compile(r"^#{1,6}\s+\S")


def extract_text_content(content: Any) -> str:
    """Extract user-visible text from strings or text-block lists."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, dict):
                parts.append(f"[{block.get('type', 'unknown')} block]")
            else:
                parts.append(str(block))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def stringify_field(value: Any) -> str:
    """Convert a trace field to string. Pass strings through, JSON-dump the rest."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def is_text_block_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(block, dict) for block in value)
        and any(block.get("type") == "text" for block in value)
    )


def _merge_heading_only_paragraphs(chunks: list[str]) -> list[str]:
    merged: list[str] = []
    i = 0
    while i < len(chunks):
        lines = chunks[i].splitlines()
        is_heading_only = len(lines) == 1 and bool(_HEADING_RE.match(lines[0]))
        if is_heading_only and i + 1 < len(chunks):
            next_lines = chunks[i + 1].splitlines()
            next_is_heading = len(next_lines) == 1 and bool(_HEADING_RE.match(next_lines[0]))
            if not next_is_heading:
                merged.append(chunks[i] + "\n\n" + chunks[i + 1])
                i += 2
                continue
        merged.append(chunks[i])
        i += 1
    return merged


def split_prompt(text: str) -> list[str]:
    """Split text on blank lines, merging orphan markdown headings into the next paragraph."""
    chunks = [chunk.strip() for chunk in text.split("\n\n") if chunk.strip()]
    if not chunks:
        return [""]
    return _merge_heading_only_paragraphs(chunks)
