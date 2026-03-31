from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal, Mapping, TypedDict

LLMProvider = Literal["anthropic", "together", "hosted_vllm"]
TierName = Literal["primary", "helper"]
InferTier = Literal["expensive", "cheap"]


class UserLlmTierSettings(TypedDict):
    provider: LLMProvider
    model_name: str
    api_base: str | None


class UserLlmSettings(TypedDict):
    primary: UserLlmTierSettings
    helper: UserLlmTierSettings


DEFAULT_USER_LLM_SETTINGS: UserLlmSettings = {
    "primary": {
        "provider": "together",
        "model_name": "Qwen/Qwen3.5-397B-A17B",
        "api_base": None,
    },
    "helper": {
        "provider": "together",
        "model_name": "Qwen/Qwen3.5-9B",
        "api_base": None,
    },
}

USER_LLM_DB_COLUMNS = {
    "primary": {
        "provider": "llm_primary_provider",
        "model_name": "llm_primary_model_name",
        "api_base": "llm_primary_api_base",
    },
    "helper": {
        "provider": "llm_helper_provider",
        "model_name": "llm_helper_model_name",
        "api_base": "llm_helper_api_base",
    },
}

LITELLM_PROVIDER_PREFIXES: dict[LLMProvider, str] = {
    "anthropic": "anthropic",
    "together": "together_ai",
    "hosted_vllm": "hosted_vllm",
}


def _trim_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _mapping_get(row: Mapping[str, Any], key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def normalize_user_llm_settings_row(row: Mapping[str, Any] | None) -> UserLlmSettings:
    settings = deepcopy(DEFAULT_USER_LLM_SETTINGS)
    if row is None:
        return settings

    for tier in ("primary", "helper"):
        default_tier = DEFAULT_USER_LLM_SETTINGS[tier]
        db_columns = USER_LLM_DB_COLUMNS[tier]
        raw_provider = _trim_text(_mapping_get(row, db_columns["provider"]))
        provider = raw_provider if raw_provider in LITELLM_PROVIDER_PREFIXES else default_tier["provider"]

        model_name = _trim_text(_mapping_get(row, db_columns["model_name"])) or default_tier["model_name"]
        api_base = _trim_text(_mapping_get(row, db_columns["api_base"]))
        if provider != "hosted_vllm":
            api_base = None

        settings[tier] = {
            "provider": provider,
            "model_name": model_name,
            "api_base": api_base,
        }

    return settings


def flatten_user_llm_settings(settings: Mapping[str, Mapping[str, Any]]) -> dict[str, str | None]:
    flattened: dict[str, str | None] = {}
    for tier in ("primary", "helper"):
        tier_settings = settings[tier]
        db_columns = USER_LLM_DB_COLUMNS[tier]
        provider = tier_settings["provider"]
        flattened[db_columns["provider"]] = provider
        flattened[db_columns["model_name"]] = tier_settings["model_name"]
        flattened[db_columns["api_base"]] = (
            tier_settings.get("api_base") if provider == "hosted_vllm" else None
        )
    return flattened


def build_litellm_request_config(
    row: Mapping[str, Any] | None,
    tier: InferTier | str = "expensive",
) -> tuple[dict[str, str], LLMProvider]:
    settings = normalize_user_llm_settings_row(row)
    tier_name: TierName = "helper" if tier == "cheap" else "primary"
    tier_settings = settings[tier_name]
    provider = tier_settings["provider"]
    request_config = {
        "model": f"{LITELLM_PROVIDER_PREFIXES[provider]}/{tier_settings['model_name']}",
    }
    if provider == "hosted_vllm" and tier_settings["api_base"]:
        request_config["api_base"] = tier_settings["api_base"]
    return request_config, provider
