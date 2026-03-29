"""Internal LLM bridge client used by the priors backend child service."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import httpx

from sovara.common.constants import HOST, PORT

_client: Optional[httpx.AsyncClient] = None
_semaphore: Optional[asyncio.Semaphore] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=f"http://{HOST}:{PORT}", timeout=35.0)
    return _client


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        max_concurrent = int(os.environ.get("SOVARA_PRIORS_LLM_MAX_CONCURRENT", "20"))
        _semaphore = asyncio.Semaphore(max_concurrent)
    return _semaphore


async def infer_structured_json(
    *,
    purpose: str,
    messages: list[dict[str, Any]],
    model: str,
    tier: str,
    response_format: dict[str, Any],
    timeout_ms: int = 30000,
    repair_attempts: int = 1,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "purpose": purpose,
        "messages": messages,
        "model": model,
        "tier": tier,
        "response_format": response_format,
        "timeout_ms": timeout_ms,
        "repair_attempts": repair_attempts,
        **extra,
    }
    sem = _get_semaphore()
    async with sem:
        response = await _get_client().post("/internal/llm/infer", json=payload)
    response.raise_for_status()
    return response.json()
