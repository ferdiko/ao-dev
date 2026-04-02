"""Helpers for computing UI-facing prior metadata from run graphs."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from sovara.runner.monkey_patching.api_parser import flatten_complete_to_show
from sovara.server.graph_models import RunGraph

_PRIORS_BLOCK_RE = re.compile(r"<sovara-priors\b[^>]*>[\s\S]*?<\/sovara-priors>", re.IGNORECASE)
_MANIFEST_RE = re.compile(r"<!--\s*(\{[\s\S]*?\})\s*-->")
_OPEN_TAG_RE = re.compile(r"^<sovara-priors\b[^>]*>\s*", re.IGNORECASE)
_CLOSE_TAG_RE = re.compile(r"\s*<\/sovara-priors>\s*$", re.IGNORECASE)
_SECTION_SPLIT_RE = re.compile(r"(?m)^##\s+")


def _unique_prior_ids(prior_ids: list[str]) -> list[str]:
    ordered: list[str] = []
    for prior_id in prior_ids:
        if prior_id and prior_id not in ordered:
            ordered.append(prior_id)
    return ordered


def _merge_prior_objects(*prior_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for priors in prior_groups:
        for prior in priors:
            prior_id = prior.get("id")
            if not isinstance(prior_id, str) or not prior_id:
                continue
            existing = by_id.get(prior_id)
            if existing is None:
                existing = {"id": prior_id}
                by_id[prior_id] = existing
                ordered.append(existing)
            for key, value in prior.items():
                if value in (None, ""):
                    continue
                if existing.get(key) in (None, ""):
                    existing[key] = value
    return ordered


def _parse_prior_manifest(block: str) -> list[str]:
    match = _MANIFEST_RE.search(block)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except (TypeError, json.JSONDecodeError):
        return []
    priors = payload.get("priors")
    if not isinstance(priors, list):
        return []
    return [
        str(item.get("id"))
        for item in priors
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
    ]


def _parse_prior_block(block: str) -> list[dict[str, Any]]:
    prior_ids = _parse_prior_manifest(block)
    inner = _OPEN_TAG_RE.sub("", block, count=1)
    inner = _CLOSE_TAG_RE.sub("", inner, count=1)
    inner = _MANIFEST_RE.sub("", inner, count=1).strip()
    if not inner:
        return [{"id": prior_id} for prior_id in prior_ids]

    sections = [section.strip() for section in _SECTION_SPLIT_RE.split(inner) if section.strip()]
    if not sections:
        return [{"id": prior_id} for prior_id in prior_ids]

    parsed: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        lines = section.splitlines()
        name = lines[0].strip() if lines else ""
        content = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        prior_id = prior_ids[index] if index < len(prior_ids) else name or f"prior-{index}"
        prior: dict[str, Any] = {"id": prior_id}
        if name:
            prior["name"] = name
        if content:
            prior["content"] = content
        parsed.append(prior)

    if len(prior_ids) > len(parsed):
        for prior_id in prior_ids[len(parsed):]:
            parsed.append({"id": prior_id})
    return parsed


def extract_effective_priors_from_node_input(node_input: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(node_input)
    except (TypeError, json.JSONDecodeError):
        return []

    if not isinstance(parsed, dict):
        return []

    to_show = parsed.get("to_show") if isinstance(parsed.get("to_show"), dict) else parsed
    flattened = flatten_complete_to_show(to_show)
    priors: list[dict[str, Any]] = []
    for value in flattened.values():
        if not isinstance(value, str) or "<sovara-priors>" not in value:
            continue
        for block in _PRIORS_BLOCK_RE.findall(value):
            priors.extend(_parse_prior_block(block))
    return _merge_prior_objects(priors)


def build_ui_prior_records(graph: RunGraph, prior_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_node_uuid = {row["node_uuid"]: dict(row) for row in prior_rows}
    parents_by_uuid: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        parents_by_uuid[edge.target_uuid].append(edge.source_uuid)

    effective_ids_by_uuid: dict[str, list[str]] = {}
    effective_priors_by_uuid: dict[str, list[dict[str, Any]]] = {}
    ui_records: dict[str, dict[str, Any]] = {}

    ordered_nodes = sorted(
        graph.nodes,
        key=lambda node: (node.step_id if node.step_id is not None else float("inf"), node.uuid),
    )

    for node in ordered_nodes:
        row = by_node_uuid.get(node.uuid)
        if row is None:
            effective_ids_by_uuid[node.uuid] = []
            effective_priors_by_uuid[node.uuid] = []
            continue

        parent_effective_priors = _merge_prior_objects(
            *[effective_priors_by_uuid.get(parent_uuid, []) for parent_uuid in parents_by_uuid.get(node.uuid, [])]
        )
        parent_effective_ids = _unique_prior_ids([prior["id"] for prior in parent_effective_priors])
        current_effective_priors = extract_effective_priors_from_node_input(node.input)
        current_effective_ids = _unique_prior_ids([prior["id"] for prior in current_effective_priors])

        fallback_effective_ids = _unique_prior_ids(
            list(row.get("inherited_prior_ids") or [])
            + [
                prior.get("id")
                for prior in row.get("applied_priors") or []
                if isinstance(prior.get("id"), str) and prior.get("id")
            ]
        )
        current_effective_ids = _unique_prior_ids(current_effective_ids + fallback_effective_ids)

        effective_priors = _merge_prior_objects(
            parent_effective_priors,
            current_effective_priors,
            row.get("applied_priors") or [],
        )
        effective_lookup = {prior["id"]: prior for prior in effective_priors if isinstance(prior.get("id"), str)}
        for prior_id in current_effective_ids:
            if prior_id not in effective_lookup:
                effective_lookup[prior_id] = {"id": prior_id}
                effective_priors.append(effective_lookup[prior_id])

        new_prior_ids = [prior_id for prior_id in current_effective_ids if prior_id not in set(parent_effective_ids)]
        new_priors = [effective_lookup.get(prior_id, {"id": prior_id}) for prior_id in new_prior_ids]

        effective_ids_by_uuid[node.uuid] = current_effective_ids
        effective_priors_by_uuid[node.uuid] = effective_priors
        row["applied_priors"] = new_priors
        row["effective_prior_ids"] = current_effective_ids
        ui_records[node.uuid] = row

    return ui_records


def attach_ui_prior_counts(graph: RunGraph, prior_rows: list[dict[str, Any]]) -> RunGraph:
    ui_records = build_ui_prior_records(graph, prior_rows)
    for node in graph.nodes:
        record = ui_records.get(node.uuid)
        node.prior_count = len(record.get("applied_priors", [])) if record is not None else None
    return graph
