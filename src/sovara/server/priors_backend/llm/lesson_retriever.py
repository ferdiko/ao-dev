"""LLM-based prior retrieval for the in-repo priors backend."""

from __future__ import annotations

import asyncio
from typing import Optional

from sovara.server.priors_backend.llm_client import infer_structured_json
from sovara.server.priors_backend.logger import logger

_RETRIEVER_SYSTEM_PROMPT = """You are a prior retrieval system.

Your job is to select priors that MAY be relevant to the user's query.

CRITICAL: Missing a relevant prior is much worse than including an irrelevant one.
- If a prior is missed, the downstream agent may repeat an avoidable mistake
- If an extra prior is included, it adds minor noise

Include a prior if ANY of these apply:
1. It addresses the topic or domain of the query
2. It describes patterns or practices relevant to the situation
3. It contains knowledge about concepts mentioned in the query
4. It warns about common mistakes in related scenarios
5. You are uncertain whether it's relevant

Only exclude priors that are clearly unrelated.
Err heavily on the side of inclusion. Your recall target is 100%."""

_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "relevant_priors",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "prior_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
            "required": ["prior_ids"],
            "additionalProperties": False,
        },
    },
}


def collect_folder_priors(store, path: str = "") -> tuple[list[tuple[str, list[dict]]], dict[str, dict]]:
    result = []
    all_priors: dict[str, dict] = {}
    data = store.list_folders(path, include_content=True)
    active_priors = [prior for prior in data["priors"] if prior.get("prior_status", "active") == "active"]

    if active_priors:
        result.append((path, active_priors))
        for prior in active_priors:
            all_priors[prior["id"]] = prior

    for folder in data.get("folders", []):
        sub_result, sub_priors = collect_folder_priors(store, folder["path"])
        result.extend(sub_result)
        all_priors.update(sub_priors)

    return result, all_priors


def build_folder_tree_summary(store, path: str = "", indent: int = 0) -> str:
    data = store.list_folders(path)
    active_count = len([prior for prior in data["priors"] if prior.get("prior_status", "active") == "active"])
    prefix = "  " * indent
    label = path or "(root)"
    lines = [f"{prefix}{label} ({active_count} priors)"]
    for folder in data.get("folders", []):
        lines.append(build_folder_tree_summary(store, folder["path"], indent + 1))
    return "\n".join(lines)


async def _query_llm_for_folder(
    priors: list[dict],
    context: str,
    model: str,
    *,
    ignore_prior_ids: set[str],
) -> list[str]:
    priors_context = "\n\n---\n\n".join(
        (
            f"ID: {prior['id']}\n"
            f"Path: {prior.get('path', '')}\n"
            f"Summary: {prior.get('summary', '')}"
        )
        for prior in priors
        if prior["id"] not in ignore_prior_ids
    )

    if not priors_context:
        return []

    result = await infer_structured_json(
        purpose="priors_retrieval",
        model=model,
        tier="cheap",
        response_format=_RESPONSE_SCHEMA,
        messages=[
            {"role": "system", "content": _RETRIEVER_SYSTEM_PROMPT},
            {"role": "user", "content": context},
            {
                "role": "user",
                "content": (
                    "Available Priors:\n"
                    f"{priors_context}\n\n"
                    "Which prior IDs are relevant to this query?"
                ),
            },
        ],
        timeout_ms=30000,
        repair_attempts=2,
    )
    return list(result["parsed"].get("prior_ids", []))


async def retrieve_relevant_priors(
    store,
    context: str,
    base_path: str = "",
    model: Optional[str] = None,
    ignore_prior_ids: Optional[list[str]] = None,
) -> list[dict]:
    folder_priors, all_priors_lookup = collect_folder_priors(store, base_path)
    if not folder_priors:
        return []

    resolved_model = model or "openai/gpt-5.4"
    ignored = set(ignore_prior_ids or [])

    logger.info(
        "[PRIORS RETRIEVER] start: %s folders, model=%s, base_path=%s",
        len(folder_priors),
        resolved_model,
        base_path or "(root)",
    )

    tasks = [
        _query_llm_for_folder(priors, context, resolved_model, ignore_prior_ids=ignored)
        for _, priors in folder_priors
    ]
    results = await asyncio.gather(*tasks)

    selected_ids: list[str] = []
    seen: set[str] = set()
    for ids in results:
        for prior_id in ids:
            if prior_id in ignored or prior_id in seen:
                continue
            if prior_id in all_priors_lookup:
                selected_ids.append(prior_id)
                seen.add(prior_id)

    return [all_priors_lookup[prior_id] for prior_id in selected_ids]
