"""Context management for the ReAct agent loop.

Provides post-consumption compaction of tool results to keep the message
history within a character budget.
"""

import logging

from .llm_backend import infer_text

logger = logging.getLogger("sovara_agent")

MAX_TOOL_RESULT_CHARS = 16000
MIN_COMPACTABLE_SIZE = 500
COMPACTED_MARKER = "[Compacted]"

COMPACT_SYSTEM = (
    "Summarize the following tool result in 1-2 sentences. "
    "Preserve specific turn numbers, verdicts, error messages, and key findings. "
    "Be concise."
)


def _is_tool_result(msg: dict) -> bool:
    return msg.get("role") == "tool"


def _is_compacted(msg: dict) -> bool:
    return COMPACTED_MARKER in msg.get("content", "")


def _summarize_tool_result(text: str, model: str) -> str:
    return infer_text(
        [{"role": "user", "content": text}],
        model=model,
        tier="cheap",
        system=COMPACT_SYSTEM,
        max_tokens=128,
    )


def compact_tool_results(
    messages: list,
    model: str,
    max_chars: int = MAX_TOOL_RESULT_CHARS,
) -> None:
    """Replace old tool results with summaries when the total exceeds max_chars.

    Mutates messages in-place. Protects the last tool result (unconsumed by
    the LLM). Skips results that are already compacted or below
    MIN_COMPACTABLE_SIZE.
    """
    tr_indices = [i for i, msg in enumerate(messages) if _is_tool_result(msg)]

    if len(tr_indices) < 2:
        return

    total = sum(len(messages[i].get("content", "")) for i in tr_indices)
    if total <= max_chars:
        return

    for i in tr_indices[:-1]:
        if total <= max_chars:
            break

        msg = messages[i]
        content = msg.get("content", "")

        if _is_compacted(msg):
            continue
        if len(content) < MIN_COMPACTABLE_SIZE:
            continue

        old_len = len(content)
        summary = _summarize_tool_result(content, model)
        msg["content"] = f"{COMPACTED_MARKER} {summary}"
        total -= old_len - len(msg["content"])

        logger.info("COMPACTED tool result at msg %d: %d -> %d chars", i, old_len, len(msg["content"]))
