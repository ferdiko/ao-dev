"""LLM-based prior retrieval for the in-repo priors backend."""

from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
import litellm
import multiprocessing
import os
import threading
from typing import Optional

from sovara.server.llm_backend import resolve_model
from sovara.server.priors_backend.llm_client import infer_structured_json
from sovara.server.priors_backend.logger import logger
_RETRIEVAL_LOG_CONTEXT_LIMIT = 4000
_RETRIEVAL_INPUT_TOKEN_LIMIT = 5000
_RETRIEVAL_TRIM_MARKER = "\n\n...[middle omitted for priors token budget]...\n\n"
_RETRIEVAL_WORKER_COUNT = max(1, int(os.environ.get("SOVARA_PRIORS_RETRIEVAL_WORKERS", "4")))
_RETRIEVAL_PROCESS_POOL: ProcessPoolExecutor | None = None
_RETRIEVAL_PROCESS_POOL_LOCK = threading.Lock()

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


def _get_retrieval_process_pool() -> ProcessPoolExecutor:
    global _RETRIEVAL_PROCESS_POOL
    if _RETRIEVAL_PROCESS_POOL is None:
        with _RETRIEVAL_PROCESS_POOL_LOCK:
            if _RETRIEVAL_PROCESS_POOL is None:
                ctx = multiprocessing.get_context("spawn")
                _RETRIEVAL_PROCESS_POOL = ProcessPoolExecutor(
                    max_workers=_RETRIEVAL_WORKER_COUNT,
                    mp_context=ctx,
                )
    return _RETRIEVAL_PROCESS_POOL


def shutdown_retrieval_process_pool() -> None:
    global _RETRIEVAL_PROCESS_POOL
    with _RETRIEVAL_PROCESS_POOL_LOCK:
        pool = _RETRIEVAL_PROCESS_POOL
        _RETRIEVAL_PROCESS_POOL = None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def _preview_text(value: str, limit: int = 400) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _preview_log_context(value: str, limit: int = _RETRIEVAL_LOG_CONTEXT_LIMIT) -> str:
    text = value or ""
    if len(text) <= limit:
        return text or "(empty)"
    return f"{text[:limit]}... ({len(text) - limit} chars truncated)"


def _format_prior_refs(priors: list[dict]) -> str:
    if not priors:
        return "(none)"
    lines = []
    for prior in priors:
        lines.append(
            f"- {prior['id']} | {prior.get('path', '')}{prior.get('name', '')} | "
            f"summary={_preview_text(str(prior.get('summary', '')), 140)}"
        )
    return "\n".join(lines)


def _format_selected_priors(priors: list[dict]) -> str:
    if not priors:
        return "(none)"
    lines = []
    for prior in priors:
        lines.append(
            f"- {prior['id']} | {prior.get('path', '')}{prior.get('name', '')}\n"
            f"  summary: {_preview_text(str(prior.get('summary', '')), 180)}\n"
            f"  content: {_preview_text(str(prior.get('content', '')), 260)}"
        )
    return "\n".join(lines)


def _build_priors_context(priors: list[dict], ignore_prior_ids: set[str]) -> str:
    return "\n\n---\n\n".join(
        (
            f"ID: {prior['id']}\n"
            f"Path: {prior.get('path', '')}\n"
            f"Summary: {prior.get('summary', '')}"
        )
        for prior in priors
        if prior["id"] not in ignore_prior_ids
    )


def _build_retrieval_messages(context: str, priors_context: str) -> list[dict[str, str]]:
    return [
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
    ]


def _estimate_prompt_tokens(model: str, messages: list[dict[str, str]]) -> int | None:
    try:
        return int(litellm.token_counter(model=model, messages=messages))
    except Exception:
        return None


def _trim_context_middle(text: str, keep_chars: int) -> str:
    if keep_chars >= len(text):
        return text
    if keep_chars <= len(_RETRIEVAL_TRIM_MARKER):
        return text[:keep_chars]
    head = keep_chars // 2
    tail = keep_chars - head
    return f"{text[:head].rstrip()}{_RETRIEVAL_TRIM_MARKER}{text[-tail:].lstrip()}"


def _fit_context_to_token_budget(context: str, priors_context: str, model: str) -> tuple[str, int | None, int | None]:
    original_messages = _build_retrieval_messages(context, priors_context)
    original_estimate = _estimate_prompt_tokens(model, original_messages)
    if original_estimate is None or original_estimate <= _RETRIEVAL_INPUT_TOKEN_LIMIT:
        return context, original_estimate, original_estimate

    ratio = min(1.0, _RETRIEVAL_INPUT_TOKEN_LIMIT / max(original_estimate, 1))
    current_ratio = max(ratio, 0.05)
    trimmed_context = context
    trimmed_estimate = original_estimate

    for _ in range(4):
        keep_chars = max(200, int(len(context) * current_ratio))
        trimmed_context = _trim_context_middle(context, keep_chars)
        trimmed_estimate = _estimate_prompt_tokens(model, _build_retrieval_messages(trimmed_context, priors_context))
        if trimmed_estimate is None or trimmed_estimate <= _RETRIEVAL_INPUT_TOKEN_LIMIT:
            break
        current_ratio *= _RETRIEVAL_INPUT_TOKEN_LIMIT / max(trimmed_estimate, 1)

    logger.warning(
        "[PRIORS RETRIEVER] trimmed context for token budget model=%s original_chars=%d trimmed_chars=%d original_prompt_tokens_est=%s trimmed_prompt_tokens_est=%s limit=%d",
        model,
        len(context),
        len(trimmed_context),
        original_estimate,
        trimmed_estimate,
        _RETRIEVAL_INPUT_TOKEN_LIMIT,
    )
    return trimmed_context, original_estimate, trimmed_estimate


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
    *,
    ignore_prior_ids: set[str],
    folder_path: str,
) -> list[str]:
    considered_priors = [prior for prior in priors if prior["id"] not in ignore_prior_ids]
    priors_context = _build_priors_context(priors, ignore_prior_ids)

    if not priors_context:
        logger.info(
            "[PRIORS RETRIEVER] folder=%s skipped after ignore filter; ignored_ids=%s",
            folder_path or "(root)",
            sorted(ignore_prior_ids),
        )
        return []

    logger.info(
        "[PRIORS RETRIEVER] folder=%s candidates=%d ignored_ids=%s\n%s",
        folder_path or "(root)",
        len(considered_priors),
        sorted(ignore_prior_ids),
        _format_prior_refs(considered_priors),
    )

    messages = _build_retrieval_messages(context, priors_context)
    result = await infer_structured_json(
        tier="cheap",
        response_format=_RESPONSE_SCHEMA,
        messages=messages,
        timeout_ms=30000,
        repair_attempts=2,
    )
    selected_ids = list(result["parsed"].get("prior_ids", []))
    logger.info(
        "[PRIORS RETRIEVER] folder=%s selected_ids=%s mode=%s model=%s",
        folder_path or "(root)",
        selected_ids,
        result.get("structured_mode"),
        result.get("model_used") or resolve_model(None, "cheap"),
    )
    return selected_ids


def _retrieve_relevant_priors_sync(
    user_id: str,
    project_id: str,
    context: str,
    base_path: str,
    ignore_prior_ids: Optional[list[str]] = None,
) -> list[dict]:
    from sovara.server.priors_backend.storage import PriorStore

    store = PriorStore(user_id, project_id)
    return asyncio.run(
        retrieve_relevant_priors(
            store=store,
            context=context,
            base_path=base_path,
            ignore_prior_ids=ignore_prior_ids,
        )
    )


async def retrieve_relevant_priors_for_scope(
    *,
    user_id: str,
    project_id: str,
    context: str,
    base_path: str = "",
    ignore_prior_ids: Optional[list[str]] = None,
) -> list[dict]:
    if os.environ.get("_SOVARA_TESTING") == "1":
        from sovara.server.priors_backend.storage import PriorStore

        store = PriorStore(user_id, project_id)
        return await retrieve_relevant_priors(
            store=store,
            context=context,
            base_path=base_path,
            ignore_prior_ids=ignore_prior_ids,
        )

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _get_retrieval_process_pool(),
        _retrieve_relevant_priors_sync,
        user_id,
        project_id,
        context,
        base_path,
        ignore_prior_ids,
    )


async def retrieve_relevant_priors(
    store,
    context: str,
    base_path: str = "",
    ignore_prior_ids: Optional[list[str]] = None,
) -> list[dict]:
    folder_priors, all_priors_lookup = collect_folder_priors(store, base_path)
    if not folder_priors:
        logger.info(
            "[PRIORS RETRIEVER] no active priors found under base_path=%s",
            base_path or "(root)",
        )
        return []

    ignored = set(ignore_prior_ids or [])
    model_used = resolve_model(None, "cheap")
    max_priors_context = max(
        (_build_priors_context(priors, ignored) for _, priors in folder_priors),
        key=len,
        default="",
    )
    trimmed_context, original_prompt_tokens_est, trimmed_prompt_tokens_est = _fit_context_to_token_budget(
        context,
        max_priors_context,
        model_used,
    )

    logger.info(
        "[PRIORS RETRIEVER] start: folders=%s model=%s base_path=%s ignored_ids=%s prompt_tokens_est=%s trimmed_prompt_tokens_est=%s\n"
        "[PRIORS RETRIEVER] context (%d chars):\n%s",
        len(folder_priors),
        model_used,
        base_path or "(root)",
        sorted(ignored),
        original_prompt_tokens_est,
        trimmed_prompt_tokens_est,
        len(trimmed_context or ""),
        _preview_log_context(trimmed_context or ""),
    )

    tasks = [
        _query_llm_for_folder(
            priors,
            trimmed_context,
            ignore_prior_ids=ignored,
            folder_path=folder_path,
        )
        for folder_path, priors in folder_priors
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

    selected_priors = [all_priors_lookup[prior_id] for prior_id in selected_ids]
    logger.info(
        "[PRIORS RETRIEVER] final selection: ids=%s\n%s",
        selected_ids,
        _format_selected_priors(selected_priors),
    )
    return selected_priors
