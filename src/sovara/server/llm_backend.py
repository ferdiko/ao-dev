import logging
import json
import time
from typing import Any

import litellm

logger = logging.getLogger("sovara_agent")

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds, doubles each retry

# Suppress litellm's own logging unless we're debugging
litellm.suppress_debug_info = True


# --- Model settings ---
# TODO: Get from settings in UI
MODEL = "anthropic/claude-sonnet-4-6"
CHEAP_MODEL = "anthropic/claude-haiku-4-5-20251001"

_TIER_MODELS = {
    "expensive": MODEL,
    "cheap": CHEAP_MODEL,
}


# --- Inference ---


def _resolve_model(model: str | None, tier: str) -> str:
    """Resolve the effective model for a request.

    `tier` remains the default routing knob, but callers may also provide an
    explicit model override. For cheap-mode requests, known flagship models can
    downshift to their smaller sibling automatically.
    """
    if not model:
        return _TIER_MODELS.get(tier, MODEL)

    if tier != "cheap":
        return model

    if model.endswith(("-mini", "-nano")):
        return model

    if model in {"openai/gpt-5.4", "gpt-5.4"}:
        return f"{model}-mini"

    return model


def infer(messages, model=None, tier="expensive", **kwargs):
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


def infer_text(messages, tier="expensive", **kwargs) -> str:
    """Sync LLM call that returns just the text content. Used by tools."""
    response = infer(messages, tier=tier, **kwargs)
    return response.choices[0].message.content or ""


class StructuredInferenceError(RuntimeError):
    """Raised when structured inference could not produce schema-valid JSON."""

    def __init__(self, message: str, *, raw_text: str = "", structured_mode: str = "failed"):
        super().__init__(message)
        self.raw_text = raw_text
        self.structured_mode = structured_mode


def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _content_item_to_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("text", "content", "value"):
            value = item.get(key)
            if isinstance(value, str):
                return value
        return ""
    for attr in ("text", "content", "value"):
        value = getattr(item, attr, None)
        if isinstance(value, str):
            return value
    return ""


def _extract_response_text(response: Any) -> str:
    choices = _get_field(response, "choices") or []
    if not choices:
        raise StructuredInferenceError("LLM response did not contain any choices")

    message = _get_field(choices[0], "message")
    if message is None:
        raise StructuredInferenceError("LLM response did not contain a message")

    content = _get_field(message, "content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text = "".join(_content_item_to_text(item) for item in content).strip()
        if text:
            return text
    text = _content_item_to_text(content).strip()
    if text:
        return text
    raise StructuredInferenceError("LLM response did not contain text content")


def _extract_json_schema(response_format: dict[str, Any] | None) -> dict[str, Any] | None:
    if not response_format:
        return None
    if response_format.get("type") == "json_object":
        return {"type": "object"}
    if response_format.get("type") != "json_schema":
        return None
    json_schema = response_format.get("json_schema") or {}
    schema = json_schema.get("schema")
    return schema if isinstance(schema, dict) else None


def _validate_schema_type(value: Any, expected_type: str, path: str) -> None:
    if expected_type == "object":
        if not isinstance(value, dict):
            raise StructuredInferenceError(f"{path} must be an object")
        return
    if expected_type == "array":
        if not isinstance(value, list):
            raise StructuredInferenceError(f"{path} must be an array")
        return
    if expected_type == "string":
        if not isinstance(value, str):
            raise StructuredInferenceError(f"{path} must be a string")
        return
    if expected_type == "boolean":
        if not isinstance(value, bool):
            raise StructuredInferenceError(f"{path} must be a boolean")
        return
    if expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise StructuredInferenceError(f"{path} must be an integer")
        return
    if expected_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StructuredInferenceError(f"{path} must be a number")
        return


def _validate_json_schema_subset(value: Any, schema: dict[str, Any] | None, path: str = "$") -> None:
    if not schema:
        return

    enum_values = schema.get("enum")
    if enum_values is not None and value not in enum_values:
        raise StructuredInferenceError(f"{path} must be one of {enum_values!r}")

    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        _validate_schema_type(value, schema_type, path)

    if schema_type == "object":
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        additional_properties = schema.get("additionalProperties", True)

        for key in required:
            if key not in value:
                raise StructuredInferenceError(f"{path}.{key} is required")

        if additional_properties is False:
            extras = sorted(key for key in value if key not in properties)
            if extras:
                raise StructuredInferenceError(f"{path} has unexpected keys: {extras}")

        for key, sub_schema in properties.items():
            if key in value:
                _validate_json_schema_subset(value[key], sub_schema, f"{path}.{key}")

        if isinstance(additional_properties, dict):
            for key, sub_value in value.items():
                if key not in properties:
                    _validate_json_schema_subset(sub_value, additional_properties, f"{path}.{key}")
        return

    if schema_type == "array":
        item_schema = schema.get("items")
        if item_schema:
            for idx, item in enumerate(value):
                _validate_json_schema_subset(item, item_schema, f"{path}[{idx}]")


def _parse_and_validate_json(raw_text: str, schema: dict[str, Any] | None) -> Any:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise StructuredInferenceError(f"LLM output was not valid JSON: {exc.msg}", raw_text=raw_text) from exc
    _validate_json_schema_subset(parsed, schema)
    return parsed


def _structured_instruction(schema: dict[str, Any] | None) -> str:
    if schema:
        schema_text = json.dumps(schema, indent=2, sort_keys=True)
        return (
            "Return ONLY valid JSON. Do not include markdown fences or explanation.\n"
            f"The JSON must satisfy this schema:\n{schema_text}"
        )
    return "Return ONLY valid JSON. Do not include markdown fences or explanation."


def _with_json_instruction(messages: list[dict[str, Any]], schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [{"role": "system", "content": _structured_instruction(schema)}] + list(messages)


def _with_repair_instruction(
    messages: list[dict[str, Any]],
    schema: dict[str, Any] | None,
    raw_text: str,
    error: str,
) -> list[dict[str, Any]]:
    return list(_with_json_instruction(messages, schema)) + [
        {"role": "assistant", "content": raw_text},
        {
            "role": "user",
            "content": (
                "Your previous response did not validate.\n"
                f"Validation error: {error}\n"
                "Return only corrected JSON that satisfies the schema."
            ),
        },
    ]


def infer_structured_json(
    messages,
    model,
    tier="expensive",
    response_format: dict[str, Any] | None = None,
    repair_attempts: int = 1,
    **kwargs,
) -> dict[str, Any]:
    """Run a structured inference request with native-first, local-validated fallback."""
    schema = _extract_json_schema(response_format)
    resolved_model = _resolve_model(model, tier)

    if response_format is not None:
        try:
            response = infer(messages, model, tier=tier, response_format=response_format, **kwargs)
            raw_text = _extract_response_text(response)
            parsed = _parse_and_validate_json(raw_text, schema)
            return {
                "raw_text": raw_text,
                "parsed": parsed,
                "structured_mode": "native",
                "model_used": resolved_model,
            }
        except StructuredInferenceError as exc:
            native_error = exc
        except Exception as exc:
            native_error = StructuredInferenceError(str(exc))
    else:
        native_error = StructuredInferenceError("No response_format provided", structured_mode="failed")

    fallback_messages = _with_json_instruction(list(messages), schema)
    last_error: StructuredInferenceError = native_error

    for attempt in range(repair_attempts + 1):
        try:
            response = infer(fallback_messages, model, tier=tier, **kwargs)
            raw_text = _extract_response_text(response)
            parsed = _parse_and_validate_json(raw_text, schema)
            return {
                "raw_text": raw_text,
                "parsed": parsed,
                "structured_mode": "local_parse" if attempt == 0 else "retry_repaired",
                "model_used": resolved_model,
            }
        except StructuredInferenceError as exc:
            last_error = exc
        except Exception as exc:
            last_error = StructuredInferenceError(str(exc))

        if attempt < repair_attempts:
            fallback_messages = _with_repair_instruction(
                list(messages),
                schema,
                last_error.raw_text,
                str(last_error),
            )

    raise StructuredInferenceError(
        f"Structured inference failed after fallback attempts: {last_error}",
        raw_text=last_error.raw_text,
        structured_mode="failed",
    )
