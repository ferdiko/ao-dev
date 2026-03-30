import logging
import time

import litellm

logger = logging.getLogger("sovara_agent")

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
