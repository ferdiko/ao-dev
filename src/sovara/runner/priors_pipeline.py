"""Helpers for strip/retrieve/inject over fully flattened ``to_show`` payloads."""

from __future__ import annotations

import json
import re
from typing import Any

from flatten_json import flatten, unflatten_list

from sovara.runner.monkey_patching.api_parser import flatten_to_show, unflatten_to_show

_PRIORS_BLOCK_RE = re.compile(r"<sovara-priors>.*?</sovara-priors>", re.DOTALL)
_MANIFEST_RE = re.compile(r"<!--\s*(\{.*?\})\s*-->", re.DOTALL)
_PRIORS_BLOCK_WITH_SEPARATOR_RE = re.compile(r"<sovara-priors>.*?</sovara-priors>\n\n", re.DOTALL)

_PREFERRED_EXACT_ANCHORS = [
    "body.system",
    "system",
    "body.instructions",
    "instructions",
    "body.input",
    "input",
]
_PROMPT_BEARING_PATTERNS = [
    re.compile(r"^body\.messages\.\d+\.content$"),
    re.compile(r"^messages\.\d+\.content$"),
    re.compile(r"^body\.input\.\d+\.content\.\d+\.text$"),
    re.compile(r"^input\.\d+\.content\.\d+\.text$"),
    re.compile(r"^system_instruction\.parts\.\d+\.text$"),
    re.compile(r"^systemInstruction\.parts\.\d+\.text$"),
    re.compile(r"^contents\.\d+\.parts\.\d+\.text$"),
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


def detect_manual_priors_reason(flattened_to_show: dict[str, Any]) -> str | None:
    """Return a reason when the payload contains user-managed priors blocks."""
    for value in flattened_to_show.values():
        if not isinstance(value, str):
            continue
        if "<sovara-priors>" not in value:
            continue

        for block_match in _PRIORS_BLOCK_RE.finditer(value):
            block = block_match.group(0)
            manifest_match = _MANIFEST_RE.search(block)
            if not manifest_match:
                return "Detected a manual <sovara-priors> block without a manifest; skipped automated priors retrieval."
            try:
                manifest = json.loads(manifest_match.group(1))
            except json.JSONDecodeError:
                return "Detected a manual <sovara-priors> block with an invalid manifest; skipped automated priors retrieval."
            if manifest.get("manual") is True:
                return "Detected a manual <sovara-priors> block; skipped automated priors retrieval."
            if not isinstance(manifest.get("priors"), list):
                return "Detected a manual <sovara-priors> block with a malformed manifest payload; skipped automated priors retrieval."

    return None


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

        cleaned[key] = strip_priors_blocks_exact(value)

    return cleaned, inherited_prior_ids, warnings


def strip_priors_blocks_exact(value: str) -> str:
    """Remove managed priors blocks without altering unrelated prompt whitespace."""
    without_prefixed_blocks = _PRIORS_BLOCK_WITH_SEPARATOR_RE.sub("", value)
    return _PRIORS_BLOCK_RE.sub("", without_prefixed_blocks)


def _flattened_key_sort_key(key: str) -> tuple[Any, ...]:
    parts: list[Any] = []
    for segment in key.split("."):
        if segment.isdigit():
            parts.append(int(segment))
        else:
            parts.append(segment)
    return tuple(parts)


def extract_prompt_bearing_keys(flattened_to_show: dict[str, Any], api_type: str) -> list[str]:
    """Return the ordered prompt-bearing keys for a flattened ``to_show`` payload."""
    del api_type  # keyed off normalized ``to_show`` keys in v1.

    ordered_keys: list[str] = []
    seen: set[str] = set()

    for key in _PREFERRED_EXACT_ANCHORS:
        value = flattened_to_show.get(key)
        if isinstance(value, str):
            ordered_keys.append(key)
            seen.add(key)

    string_keys = sorted(
        (
            key
            for key, value in flattened_to_show.items()
            if isinstance(value, str) and key not in seen
        ),
        key=_flattened_key_sort_key,
    )
    for key in string_keys:
        if any(pattern.match(key) for pattern in _PROMPT_BEARING_PATTERNS):
            ordered_keys.append(key)
            seen.add(key)

    return ordered_keys


def extract_prompt_bearing_pairs(flattened_to_show: dict[str, Any], api_type: str) -> list[dict[str, str]]:
    """Return ordered prompt-bearing ``(key, value)`` pairs for matching and replay."""
    return [
        {"key": key, "value": flattened_to_show[key]}
        for key in extract_prompt_bearing_keys(flattened_to_show, api_type)
    ]


def render_retrieval_context(input_delta: list[dict[str, Any]]) -> str:
    """Serialize prompt-bearing suffix entries into the retriever-facing context string."""
    lines: list[str] = []
    for entry in input_delta:
        value = entry.get("value")
        if isinstance(value, str):
            value_text = value
        else:
            value_text = json.dumps(value, sort_keys=True, ensure_ascii=False)
        lines.append(f"{entry['key']}: {value_text}")
    return "\n".join(lines)


def replay_injected_prefix(
    flattened_to_show: dict[str, Any],
    injected_prefix_pairs: list[dict[str, str]],
) -> dict[str, Any]:
    """Replay a cached injected prompt prefix onto a clean flattened mapping."""
    updated = dict(flattened_to_show)
    for pair in injected_prefix_pairs:
        key = pair.get("key")
        value = pair.get("value")
        if isinstance(key, str) and isinstance(value, str):
            updated[key] = value
    return updated


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
