"""Helpers for strip/delta/retrieve/inject over fully flattened ``to_show`` payloads."""

from __future__ import annotations

import json
import re
from typing import Any

from flatten_json import flatten, unflatten_list

from sovara.runner.monkey_patching.api_parser import flatten_to_show, unflatten_to_show

_PRIORS_BLOCK_RE = re.compile(r"<sovara-priors>.*?</sovara-priors>", re.DOTALL)
_MANIFEST_RE = re.compile(r"<!--\s*(\{.*?\})\s*-->", re.DOTALL)
_COLLAPSE_BLANKS_RE = re.compile(r"\n{3,}")

_PREFERRED_EXACT_ANCHORS = [
    "body.system",
    "system",
    "body.instructions",
    "instructions",
]
_FALLBACK_ANCHOR_PATTERNS = [
    re.compile(r"^body\.messages\.0\.content$"),
    re.compile(r"^messages\.0\.content$"),
    re.compile(r"^body\.input\.0\.content\.0\.text$"),
    re.compile(r"^input\.0\.content\.0\.text$"),
    re.compile(r"^system_instruction\.parts\.0\.text$"),
    re.compile(r"^systemInstruction\.parts\.0\.text$"),
    re.compile(r"^contents\.0\.parts\.0\.text$"),
]


def flatten_complete_to_show(to_show: dict[str, Any] | list[Any] | str | None) -> dict[str, Any]:
    """Fully flatten a stored ``to_show`` payload, including list indices."""
    if to_show is None:
        return {}
    if isinstance(to_show, dict):
        nested = unflatten_to_show(to_show)
        return flatten(nested, ".")
    if isinstance(to_show, list):
        return flatten(to_show, ".")
    return {"value": to_show}


def restore_to_show_from_flattened(flattened_to_show: dict[str, Any]) -> dict[str, Any] | list[Any] | str | None:
    """Rebuild the stored ``to_show`` representation from a fully flattened mapping."""
    if not flattened_to_show:
        return {}
    if set(flattened_to_show.keys()) == {"value"}:
        return flattened_to_show["value"]
    nested = unflatten_list(flattened_to_show, ".")
    return flatten_to_show(nested)


def parse_inherited_prior_ids(value: str) -> tuple[list[str], list[str]]:
    """Extract inherited prior ids from a rendered priors block."""
    inherited_prior_ids: list[str] = []
    warnings: list[str] = []

    for block_match in _PRIORS_BLOCK_RE.finditer(value):
        block = block_match.group(0)
        manifest_match = _MANIFEST_RE.search(block)
        if not manifest_match:
            warnings.append("Stripped a manual <sovara-priors> block without a manifest.")
            continue

        try:
            manifest = json.loads(manifest_match.group(1))
        except json.JSONDecodeError:
            warnings.append("Stripped a <sovara-priors> block with an invalid manifest.")
            continue

        priors = manifest.get("priors")
        if not isinstance(priors, list):
            warnings.append("Stripped a <sovara-priors> block with a malformed manifest payload.")
            continue

        for prior in priors:
            if not isinstance(prior, dict):
                continue
            prior_id = prior.get("id")
            if isinstance(prior_id, str) and prior_id and prior_id not in inherited_prior_ids:
                inherited_prior_ids.append(prior_id)

    return inherited_prior_ids, warnings


def strip_priors_from_flattened(flattened_to_show: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    """Strip priors blocks from every string value in a flattened mapping."""
    cleaned = dict(flattened_to_show)
    inherited_prior_ids: list[str] = []
    warnings: list[str] = []

    for key, value in flattened_to_show.items():
        if not isinstance(value, str) or "<sovara-priors>" not in value:
            continue

        ids, parse_warnings = parse_inherited_prior_ids(value)
        for prior_id in ids:
            if prior_id not in inherited_prior_ids:
                inherited_prior_ids.append(prior_id)
        warnings.extend(parse_warnings)

        stripped = _PRIORS_BLOCK_RE.sub("", value)
        stripped = _COLLAPSE_BLANKS_RE.sub("\n\n", stripped).strip()
        cleaned[key] = stripped

    return cleaned, inherited_prior_ids, warnings


def _value_fingerprint(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def build_input_delta(
    current_flattened_to_show: dict[str, Any],
    parent_flattened_to_shows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return entries whose values do not already appear anywhere in parent contexts."""
    parent_flattened_to_shows = parent_flattened_to_shows or []
    seen_parent_values = {
        _value_fingerprint(value)
        for parent in parent_flattened_to_shows
        for value in parent.values()
    }

    delta_entries: list[dict[str, Any]] = []
    for key, value in current_flattened_to_show.items():
        if _value_fingerprint(value) in seen_parent_values:
            continue
        delta_entries.append({"key": key, "value": value})

    return delta_entries


def render_retrieval_context(input_delta: list[dict[str, Any]]) -> str:
    """Serialize delta entries into the retriever-facing context string."""
    lines: list[str] = []
    for entry in input_delta:
        value = entry.get("value")
        if isinstance(value, str):
            value_text = value
        else:
            value_text = json.dumps(value, sort_keys=True, ensure_ascii=False)
        lines.append(f"{entry['key']}: {value_text}")
    return "\n".join(lines)


def resolve_injection_anchor(flattened_to_show: dict[str, Any], api_type: str) -> dict[str, Any] | None:
    """Resolve a provider-approved prompt-bearing anchor from flattened ``to_show`` keys."""
    del api_type  # Anchor selection is keyed off normalized ``to_show`` keys in v1.

    for key in _PREFERRED_EXACT_ANCHORS:
        value = flattened_to_show.get(key)
        if isinstance(value, str):
            return {"key": key}

    string_keys = sorted(
        key for key, value in flattened_to_show.items()
        if isinstance(value, str)
    )
    for pattern in _FALLBACK_ANCHOR_PATTERNS:
        for key in string_keys:
            if pattern.match(key):
                return {"key": key}

    return None


def inject_priors_block(
    flattened_to_show: dict[str, Any],
    rendered_priors_block: str,
    injection_anchor: dict[str, Any],
) -> dict[str, Any]:
    """Inject priors into the approved anchor field of a flattened mapping."""
    key = injection_anchor.get("key")
    if not isinstance(key, str):
        raise ValueError("Injection anchor must contain a string 'key'.")
    if key not in flattened_to_show or not isinstance(flattened_to_show[key], str):
        raise ValueError(f"Injection anchor '{key}' does not point to a string field.")

    updated = dict(flattened_to_show)
    original = updated[key]
    updated[key] = f"{rendered_priors_block}\n\n{original}" if original else rendered_priors_block
    return updated
