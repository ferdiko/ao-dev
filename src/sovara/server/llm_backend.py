import logging
import json
import math
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Callable, Sequence, TypeVar

import litellm
from sovara.common.constants import MAIN_SERVER_LOG, TRACE_CHAT_SCATTER_BUDGET_SECONDS
from sovara.common.logger import create_file_logger

logger = create_file_logger(MAIN_SERVER_LOG, logger_name="sovara_agent", level=logging.INFO)
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
# MODEL = "together_ai/Qwen/Qwen3.5-397B-A17B"
# CHEAP_MODEL = "together_ai/Qwen/Qwen3.5-9B"
MODEL = "together_ai/Qwen/Qwen3.5-397B-A17B"
CHEAP_MODEL = "gpt-5.4-mini"

_TIER_MODELS = {
    "expensive": MODEL,
    "cheap": CHEAP_MODEL,
}
NO_THINKING_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}
_QWEN_REASONING_MAX_TOKENS = 1024


def _log_preview(value, max_len: int = 800) -> str:
    text = " ".join(repr(value).split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _preview_text(value: str, max_len: int = 2000) -> str:
    text = (value or "").strip()
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


def _preview_json(value: Any, max_len: int = 2000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = repr(value)
    return _preview_text(text, max_len=max_len)


def _payload_issue_paths(value: Any, path: str = "$") -> list[str]:
    issues: list[str] = []
    if isinstance(value, float) and not math.isfinite(value):
        issues.append(f"{path}=non_finite_float({value!r})")
        return issues
    if isinstance(value, str):
        surrogate_count = sum(1 for ch in value if 0xD800 <= ord(ch) <= 0xDFFF)
        control_count = sum(1 for ch in value if ord(ch) < 32 and ch not in "\n\r\t")
        if surrogate_count:
            issues.append(f"{path}=contains_{surrogate_count}_surrogates")
        if control_count:
            issues.append(f"{path}=contains_{control_count}_control_chars")
        return issues
    if isinstance(value, dict):
        for key, sub_value in value.items():
            issues.extend(_payload_issue_paths(sub_value, f"{path}.{key}"))
        return issues
    if isinstance(value, list):
        for idx, item in enumerate(value):
            issues.extend(_payload_issue_paths(item, f"{path}[{idx}]"))
        return issues
    return issues


def _message_debug_summary(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for idx, message in enumerate(messages):
        content = message.get("content")
        if isinstance(content, str):
            summary.append(
                {
                    "index": idx,
                    "role": message.get("role"),
                    "content_type": "str",
                    "content_chars": len(content),
                    "content_preview": _preview_text(content, 600),
                }
            )
        else:
            summary.append(
                {
                    "index": idx,
                    "role": message.get("role"),
                    "content_type": type(content).__name__,
                    "content_preview": _preview_json(content, 600),
                }
            )
    return summary


def _serialize_payload_debug(model: str, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> tuple[str | None, str | None]:
    payload = {"model": model, "messages": messages, **kwargs}
    try:
        return json.dumps(payload, ensure_ascii=False, allow_nan=False), None
    except Exception as exc:
        return None, str(exc)


def _is_invalid_json_body_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "could not parse the json body" in text


def _log_invalid_json_body_diagnostics(model: str, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> None:
    payload_json, serialization_error = _serialize_payload_debug(model, messages, kwargs)
    payload = {"model": model, "messages": messages, **kwargs}
    logger.error(
        "infer invalid-json-body diagnostics model=%s payload_serialization_error=%s payload_issues=%s message_summary=%s payload_preview=%s",
        model,
        serialization_error,
        _payload_issue_paths(payload),
        _preview_json(_message_debug_summary(messages), 4000),
        _preview_text(payload_json, 8000) if payload_json is not None else _preview_json(payload, 8000),
    )


def _safe_token_counter(model: str, messages: list[dict[str, Any]]) -> int | None:
    try:
        return int(litellm.token_counter(model=model, messages=messages))
    except Exception:
        return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_usage_metrics(response: Any) -> dict[str, int | None]:
    usage = _get_field(response, "usage")
    if usage is None:
        return {
            "prompt_tokens": None,
            "completion_tokens": None,
            "reasoning_tokens": None,
            "total_tokens": None,
        }

    completion_details = _get_field(usage, "completion_tokens_details")
    reasoning_tokens = _coerce_int(_get_field(completion_details, "reasoning_tokens"))
    return {
        "prompt_tokens": _coerce_int(_get_field(usage, "prompt_tokens")),
        "completion_tokens": _coerce_int(_get_field(usage, "completion_tokens")),
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": _coerce_int(_get_field(usage, "total_tokens")),
    }


def _bounded_max_tokens(kwargs: dict[str, Any], cap: int) -> int:
    existing = _coerce_int(kwargs.get("max_tokens"))
    if existing is None:
        return cap
    return min(existing, cap)


def _merge_extra_body(kwargs: dict[str, Any], extra_body: dict[str, Any]) -> dict[str, Any]:
    merged = dict(kwargs)
    existing = merged.get("extra_body")
    if isinstance(existing, dict):
        merged["extra_body"] = {**existing, **extra_body}
    else:
        merged["extra_body"] = dict(extra_body)
    return merged


def _provider_name(model: str) -> str | None:
    try:
        _, provider, _, _ = litellm.get_llm_provider(model)
        return provider
    except Exception:
        return None


def _supports_reasoning_effort(model: str) -> bool:
    provider = _provider_name(model)
    return provider in {"openai", "anthropic"}


def _is_qwen_model(model: str) -> bool:
    return "qwen" in (model or "").lower()


def _with_structured_reasoning_kwargs(model: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    if "reasoning_effort" in kwargs or not _supports_reasoning_effort(model):
        return dict(kwargs)
    updated = dict(kwargs)
    updated["reasoning_effort"] = "low"
    return updated


def _is_non_retryable_infer_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return 400 <= status_code < 500 and status_code != 429
    return type(exc).__name__ == "BadRequestError"


# --- Inference ---


def resolve_model(model: str | None, tier: str) -> str:
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
    resolved = resolve_model(model, tier)
    kwargs.pop("purpose", None)
    if kwargs.get("reasoning_effort") not in {None, "none"}:
        kwargs.pop("temperature", None)
    else:
        kwargs.setdefault("temperature", 0)

    # Normalize system= kwarg into a system message for cross-provider compat
    system = kwargs.pop("system", None)
    if system:
        messages = [{"role": "system", "content": system}] + list(messages)

    prompt_tokens_estimate = _safe_token_counter(resolved, list(messages))

    for attempt in range(MAX_RETRIES):
        started_at = time.perf_counter()
        try:
            response = litellm.completion(
                model=resolved,
                messages=messages,
                **kwargs,
            )
            return response
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.warning(
                "infer failed model=%s tier=%s messages=%d prompt_tokens_est=%s completion_tokens=%s reasoning_tokens=%s total_tokens=%s elapsed_ms=%d attempt=%d/%d",
                resolved,
                tier,
                len(messages),
                prompt_tokens_estimate,
                None,
                None,
                None,
                elapsed_ms,
                attempt + 1,
                MAX_RETRIES,
            )
            if _is_invalid_json_body_error(exc):
                _log_invalid_json_body_diagnostics(resolved, list(messages), dict(kwargs))
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
            if _is_non_retryable_infer_error(exc):
                raise
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
    resolved = resolve_model(kwargs.get("model"), tier)
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


def _supports_native_response_format(model: str, response_format: dict[str, Any] | None) -> bool:
    if not response_format:
        return False

    try:
        _, provider, _, _ = litellm.get_llm_provider(model)
        support_kwargs = {"model": model, "custom_llm_provider": provider}
    except Exception:
        support_kwargs = {"model": model}

    try:
        if response_format.get("type") == "json_schema":
            return bool(litellm.supports_response_schema(**support_kwargs))

        supported_params = litellm.get_supported_openai_params(
            request_type="chat_completion",
            **support_kwargs,
        ) or []
        return "response_format" in supported_params
    except Exception as exc:
        logger.debug(
            "Could not determine native structured-output support for model=%s: %s",
            model,
            exc,
        )
        return False


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


def _strip_code_fences(raw_text: str) -> str:
    text = (raw_text or "").strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _extract_first_balanced_json(raw_text: str) -> str | None:
    text = raw_text or ""
    start = None
    stack: list[str] = []
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if start is None:
            if char in "{[":
                start = index
                stack = ["}" if char == "{" else "]"]
            continue

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char in "{[":
            stack.append("}" if char == "{" else "]")
            continue

        if char in "}]":
            if not stack or char != stack[-1]:
                return None
            stack.pop()
            if not stack and start is not None:
                return text[start : index + 1]

    return None


def _candidate_json_strings(raw_text: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []

    def add(label: str, candidate: str | None) -> None:
        if not candidate:
            return
        normalized = candidate.strip()
        if not normalized:
            return
        if any(existing == normalized for _, existing in candidates):
            return
        candidates.append((label, normalized))

    stripped = _strip_code_fences(raw_text)
    add("raw", raw_text)
    if stripped != (raw_text or "").strip():
        add("stripped_fence", stripped)
    add("balanced_raw", _extract_first_balanced_json(raw_text))
    add("balanced_stripped", _extract_first_balanced_json(stripped))
    return candidates


def _schema_example_value(schema: dict[str, Any] | None) -> Any:
    if not schema:
        return {}
    schema_type = schema.get("type")
    if schema_type == "string":
        return "example"
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0
    if schema_type == "boolean":
        return False
    if schema_type == "array":
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else None
        item_type = item_schema.get("type") if item_schema else None
        if item_type == "string":
            return ["p1", "p2"]
        return [_schema_example_value(item_schema)]
    if schema_type == "object":
        properties = schema.get("properties") or {}
        return {key: _schema_example_value(sub_schema) for key, sub_schema in properties.items()}
    return {}


def _schema_example(schema: dict[str, Any] | None) -> str | None:
    if not schema:
        return None
    try:
        return json.dumps(_schema_example_value(schema), ensure_ascii=False)
    except Exception:
        return None


def _coerce_to_schema_shape(parsed: Any, schema: dict[str, Any] | None) -> Any:
    if not schema or isinstance(parsed, dict) or schema.get("type") != "object":
        return parsed
    properties = schema.get("properties") or {}
    if len(properties) != 1:
        return parsed
    key, sub_schema = next(iter(properties.items()))
    try:
        _validate_json_schema_subset(parsed, sub_schema, f"$.{key}")
    except StructuredInferenceError:
        return parsed
    return {key: parsed}


def _parse_and_validate_json(raw_text: str, schema: dict[str, Any] | None) -> Any:
    last_decode_error: json.JSONDecodeError | None = None
    for strategy, candidate in _candidate_json_strings(raw_text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_decode_error = exc
            logger.warning(
                "structured parse failed stage=json_decode strategy=%s error=%s raw_text=%s",
                strategy,
                exc.msg,
                _preview_text(candidate),
            )
            continue

        coerced = _coerce_to_schema_shape(parsed, schema)
        if coerced is not parsed:
            parsed = coerced
        try:
            _validate_json_schema_subset(parsed, schema)
        except StructuredInferenceError as exc:
            logger.warning(
                "structured parse failed stage=schema_validation strategy=%s error=%s raw_text=%s parsed=%s",
                strategy,
                str(exc),
                _preview_text(candidate),
                _preview_json(parsed),
            )
            raise StructuredInferenceError(str(exc), raw_text=candidate, structured_mode=exc.structured_mode) from exc
        return parsed

    error = last_decode_error.msg if last_decode_error is not None else "no JSON object or array found"
    raise StructuredInferenceError(f"LLM output was not valid JSON: {error}", raw_text=raw_text)


def _structured_instruction(schema: dict[str, Any] | None) -> str:
    if schema:
        schema_text = json.dumps(schema, indent=2, sort_keys=True)
        instruction = (
            "Return ONLY valid JSON. Do not include markdown fences or explanation.\n"
            f"The JSON must satisfy this schema:\n{schema_text}"
        )
        example = _schema_example(schema)
        if example:
            instruction += f"\nExample valid JSON:\n{example}"
        return instruction
    return "Return ONLY valid JSON. Do not include markdown fences or explanation."


def _with_json_instruction(messages: list[dict[str, Any]], schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    instruction = _structured_instruction(schema)
    normalized = list(messages)
    if normalized and normalized[0].get("role") == "system":
        merged = dict(normalized[0])
        original = merged.get("content")
        if isinstance(original, str) and original:
            merged["content"] = f"{instruction}\n\n{original}"
        else:
            merged["content"] = instruction
        return [merged, *normalized[1:]]
    return [{"role": "system", "content": instruction}, *normalized]


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


def _with_qwen_reflection_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(messages) + [
        {
            "role": "user",
            "content": (
                "Think through the answer carefully before responding. "
                "Use this turn only for reasoning and keep it concise."
            ),
        }
    ]


def _with_qwen_answer_prompt(
    messages: list[dict[str, Any]],
    schema: dict[str, Any] | None,
    reflection_text: str,
) -> list[dict[str, Any]]:
    return list(messages) + [
        {"role": "assistant", "content": reflection_text},
        {
            "role": "user",
            "content": (
                "Now that you have thought about it, give the final answer.\n"
                f"{_structured_instruction(schema)}"
            ),
        },
    ]


def infer_structured_json(
    messages,
    model: str | None,
    tier="expensive",
    response_format: dict[str, Any] | None = None,
    repair_attempts: int = 1,
    **kwargs,
) -> dict[str, Any]:
    """Run a structured inference request with native-first, local-validated fallback."""
    schema = _extract_json_schema(response_format)
    resolved_model = resolve_model(model, tier)
    native_supported = _supports_native_response_format(resolved_model, response_format)
    structured_kwargs = _with_structured_reasoning_kwargs(resolved_model, dict(kwargs))

    if response_format is not None and native_supported:
        try:
            response = infer(messages, model=model, tier=tier, response_format=response_format, **structured_kwargs)
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
    elif response_format is not None:
        native_error = StructuredInferenceError(
            f"Native structured output unsupported for model {resolved_model}",
            structured_mode="failed",
        )
    else:
        native_error = StructuredInferenceError("No response_format provided", structured_mode="failed")

    if _is_qwen_model(resolved_model):
        reflection_kwargs = dict(structured_kwargs)
        reflection_kwargs["max_tokens"] = _bounded_max_tokens(reflection_kwargs, _QWEN_REASONING_MAX_TOKENS)
        try:
            reflection_messages = _with_qwen_reflection_prompt(list(messages))
            reflection_response = infer(
                reflection_messages,
                model=model,
                tier=tier,
                **reflection_kwargs,
            )
            reflection_text = _extract_response_text(reflection_response)
            answer_kwargs = _merge_extra_body(structured_kwargs, NO_THINKING_EXTRA_BODY)
            answer_kwargs["max_tokens"] = _bounded_max_tokens(answer_kwargs, _QWEN_REASONING_MAX_TOKENS)
            answer_messages = _with_qwen_answer_prompt(list(messages), schema, reflection_text)
            response = infer(
                answer_messages,
                model=model,
                tier=tier,
                **answer_kwargs,
            )
            raw_text = _extract_response_text(response)
            parsed = _parse_and_validate_json(raw_text, schema)
            return {
                "raw_text": raw_text,
                "parsed": parsed,
                "structured_mode": "qwen_two_turn",
                "model_used": resolved_model,
            }
        except StructuredInferenceError as exc:
            native_error = exc
        except Exception as exc:
            native_error = StructuredInferenceError(str(exc))

    fallback_messages = _with_json_instruction(list(messages), schema)
    last_error: StructuredInferenceError = native_error

    for attempt in range(repair_attempts + 1):
        try:
            response = infer(fallback_messages, model=model, tier=tier, **structured_kwargs)
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
