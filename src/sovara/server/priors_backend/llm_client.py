"""Shared LLM bridge helpers used by priors retrieval and validation."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        max_concurrent = int(os.environ.get("SOVARA_PRIORS_LLM_MAX_CONCURRENT", "20"))
        _semaphore = asyncio.Semaphore(max_concurrent)
    return _semaphore


async def infer_structured_json(
    *,
    messages: list[dict[str, Any]],
    tier: str,
    response_format: dict[str, Any],
    timeout_ms: int = 30000,
    repair_attempts: int = 1,
    **extra: Any,
) -> dict[str, Any]:
    from sovara.server.llm_backend import infer_structured_json as _infer_structured_json

    sem = _get_semaphore()
    async with sem:
        return await asyncio.to_thread(
            _infer_structured_json,
            messages,
            None,
            tier=tier,
            response_format=response_format,
            repair_attempts=repair_attempts,
            timeout=max(timeout_ms / 1000.0, 0.001),
            **extra,
        )
