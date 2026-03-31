import logging
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Callable, Sequence, TypeVar

import litellm
from sovara.common.constants import TRACE_CHAT_SCATTER_BUDGET_SECONDS

logger = logging.getLogger("sovara_agent")
T = TypeVar("T")
R = TypeVar("R")

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds, doubles each retry

# Suppress litellm's own logging unless we're debugging
litellm.suppress_debug_info = True


# --- Model settings ---
# TODO: Get from settings in UI
# MODEL = "anthropic/claude-sonnet-4-6"
# CHEAP_MODEL = "anthropic/claude-haiku-4-5-20251001"
MODEL = "together_ai/Qwen/Qwen3.5-397B-A17B"
CHEAP_MODEL = "together_ai/Qwen/Qwen3.5-9B"

_TIER_MODELS = {
    "expensive": MODEL,
    "cheap": CHEAP_MODEL,
}
NO_THINKING_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}


def _log_preview(value, max_len: int = 800) -> str:
    text = " ".join(repr(value).split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# --- Inference ---


def infer(messages, tier="expensive", **kwargs):
    """Sync LLM call via litellm. Returns the full response object."""
    kwargs.setdefault("temperature", 0)
    resolved = _TIER_MODELS.get(tier, MODEL)

    # Normalize system= kwarg into a system message for cross-provider compat
    system = kwargs.pop("system", None)
    if system:
        messages = [{"role": "system", "content": system}] + list(messages)

    for attempt in range(MAX_RETRIES):
        try:
            return litellm.completion(
                model=resolved,
                messages=messages,
                **kwargs,
            )
        except Exception:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.exception(
                "infer error attempt=%d/%d model=%s tier=%s messages=%d kwargs=%s",
                attempt + 1,
                MAX_RETRIES,
                resolved,
                tier,
                len(messages),
                _log_preview(kwargs),
            )
            if attempt + 1 == MAX_RETRIES:
                raise
            logger.warning(
                "infer retrying after %.1fs model=%s tier=%s",
                delay,
                resolved,
                tier,
            )
            time.sleep(delay)


def infer_text(messages, tier="expensive", **kwargs) -> str:
    """Sync LLM call that returns just the text content. Used by tools."""
    response = infer(messages, tier=tier, **kwargs)
    resolved = _TIER_MODELS.get(tier, MODEL)
    choices = getattr(response, "choices", None) or []
    choice = choices[0] if choices else None
    message = getattr(choice, "message", None) if choice is not None else None
    content = getattr(message, "content", None) or ""

    if not content:
        finish_reason = getattr(choice, "finish_reason", None) if choice is not None else None
        tool_calls = getattr(message, "tool_calls", None) if message is not None else None
        reasoning_content = getattr(message, "reasoning_content", None) if message is not None else None
        logger.warning(
            "infer_text empty content model=%s tier=%s finish_reason=%r tool_calls=%d reasoning_chars=%d response=%s",
            getattr(response, "model", None) or resolved,
            tier,
            finish_reason,
            len(tool_calls or []),
            len(reasoning_content or ""),
            _log_preview(message if message is not None else response),
        )
        logger.warning("infer_text empty content full_response=%r", response)

    return content


def scatter_execute(
    items: Sequence[T],
    run_one: Callable[[T], R],
    *,
    max_workers: int | None = None,
    budget_seconds: float = TRACE_CHAT_SCATTER_BUDGET_SECONDS,
    on_result: Callable[[T, R], None] | None = None,
    on_exception: Callable[[T, Exception], None] | None = None,
    on_timeout: Callable[[list[T]], None] | None = None,
) -> list[R | None]:
    """Run independent jobs in parallel until a shared deadline.

    Returns one entry per input item in the original order. Successful runs
    contain their result; failed or timed-out runs contain None so callers can
    apply their own domain-specific fallback.
    """
    if not items:
        return []

    worker_count = len(items) if max_workers is None else max_workers
    worker_count = max(1, min(worker_count, len(items)))
    results: list[R | None] = [None] * len(items)
    finished: set[int] = set()
    future_to_index: dict = {}
    executor = None

    try:
        executor = ThreadPoolExecutor(max_workers=worker_count)
        future_to_index = {
            executor.submit(run_one, item): idx
            for idx, item in enumerate(items)
        }
        deadline = time.monotonic() + budget_seconds

        while future_to_index:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            done, _ = wait(
                tuple(future_to_index),
                timeout=remaining,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                break
            for future in done:
                idx = future_to_index.pop(future)
                item = items[idx]
                try:
                    result = future.result()
                except Exception as exc:
                    finished.add(idx)
                    if on_exception:
                        on_exception(item, exc)
                else:
                    results[idx] = result
                    finished.add(idx)
                    if on_result:
                        on_result(item, result)
    finally:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    timed_out = [items[idx] for idx in range(len(items)) if idx not in finished]
    if timed_out and on_timeout:
        on_timeout(timed_out)

    return results
