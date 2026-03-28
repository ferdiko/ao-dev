import logging
import time

import litellm

logger = logging.getLogger("sovara_agent")

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds, doubles each retry

# Suppress litellm's own logging unless we're debugging
litellm.suppress_debug_info = True


# --- Model tier settings ---
# Maps a model to its cheap counterpart. The expensive tier always uses the
# model as given. Add entries here to route tier="cheap" calls to smaller models.
CHEAP_TIER = {
    "anthropic/claude-sonnet-4-6": "anthropic/claude-haiku-4-5-20251001",
    "openai/gpt-5.4": "openai/gpt-5.4-mini",
    # vLLM / local models: no cheap override — uses the same model
}


def _resolve_model(model: str, tier: str) -> str:
    if tier == "cheap":
        return CHEAP_TIER.get(model, model)
    return model


# --- Inference ---


def infer(messages, model, tier="expensive", **kwargs):
    """Sync LLM call via litellm. Returns the full response object."""
    kwargs.setdefault("temperature", 0)
    resolved = _resolve_model(model, tier)

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
        except Exception as e:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning("infer error (attempt %d/%d): %s", attempt + 1, MAX_RETRIES, e)
            if attempt + 1 == MAX_RETRIES:
                raise
            time.sleep(delay)


def infer_text(messages, model, tier="expensive", **kwargs) -> str:
    """Sync LLM call that returns just the text content. Used by tools."""
    response = infer(messages, model, tier=tier, **kwargs)
    return response.choices[0].message.content or ""
