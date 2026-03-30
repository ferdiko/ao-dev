"""Runtime priors helpers and the legacy manual priors injection API."""

from copy import deepcopy
from dataclasses import dataclass, field
import json
import time
import urllib.error
import urllib.request
from typing import Any, List, Optional

import httpx

from sovara.common.constants import PRIORS_SERVER_URL
from sovara.common.logger import logger
from sovara.common.utils import http_post
from sovara.runner.context_manager import get_run_id
from sovara.runner.monkey_patching.api_parser import (
    func_kwargs_to_json_str,
    json_str_to_original_inp_dict,
    merge_filtered_into_raw,
)
from sovara.runner.priors_pipeline import (
    extract_prompt_bearing_pairs,
    flatten_complete_to_show,
    inject_priors_block,
    replay_injected_prefix,
    render_retrieval_context,
    restore_to_show_from_flattened,
    strip_priors_from_flattened,
)
from sovara.server.database_manager import DB

_INTERNAL_PRIORS_TIMEOUT_MS = 30000
_INTERNAL_PRIORS_HTTP_TIMEOUT_S = (_INTERNAL_PRIORS_TIMEOUT_MS / 1000.0) + 5.0
_INTERNAL_PREFIX_CACHE_TIMEOUT_MS = 10000
_INTERNAL_PREFIX_CACHE_HTTP_TIMEOUT_S = (_INTERNAL_PREFIX_CACHE_TIMEOUT_MS / 1000.0) + 5.0


@dataclass(slots=True)
class PriorRuntimeMetadata:
    status: str
    retrieval_context: str = ""
    inherited_prior_ids: list[str] = field(default_factory=list)
    applied_priors: list[dict[str, Any]] = field(default_factory=list)
    rendered_priors_block: str = ""
    injection_anchor: dict[str, Any] | None = None
    model: str | None = None
    timeout_ms: int = _INTERNAL_PRIORS_TIMEOUT_MS
    latency_ms: int | None = None
    warning_message: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class PriorPreparationResult:
    executed_input_dict: dict[str, Any]
    input_delta_json: str
    metadata: PriorRuntimeMetadata


def _runtime_log(level: str, message: str, **details: Any) -> None:
    log_method = getattr(logger, level)
    if details:
        detail_text = json.dumps(details, sort_keys=True, ensure_ascii=False)
        log_method("%s | %s", message, detail_text)
    else:
        log_method(message)

def _unique_prior_ids(prior_ids: list[str]) -> list[str]:
    ordered_unique: list[str] = []
    for prior_id in prior_ids:
        if prior_id and prior_id not in ordered_unique:
            ordered_unique.append(prior_id)
    return ordered_unique


def _lookup_longest_prefix_cache_hit(
    run_id: str,
    clean_pairs: list[dict[str, str]],
) -> tuple[dict[str, Any] | None, int]:
    if not run_id or not clean_pairs:
        return None, 0
    try:
        response = http_post(
            "/internal/priors/prefix-cache/lookup",
            {
                "run_id": run_id,
                "base_path": "",
                "clean_pairs": clean_pairs,
            },
            timeout=_INTERNAL_PREFIX_CACHE_HTTP_TIMEOUT_S,
        )
    except Exception as exc:
        _runtime_log("warning", "[PRIORS RUNTIME] prefix lookup failed", error=str(exc))
        return None, 0

    if not response.get("found"):
        return None, 0
    matched_pair_count = int(response.get("matched_pair_count") or 0)
    if matched_pair_count <= 0:
        return None, 0
    return response, matched_pair_count


def _store_prefix_cache_entry(
    run_id: str | None,
    clean_pairs: list[dict[str, str]],
    injected_pairs: list[dict[str, str]],
    prior_ids: list[str],
) -> None:
    if not run_id or not clean_pairs:
        return
    try:
        http_post(
            "/internal/priors/prefix-cache/store",
            {
                "run_id": run_id,
                "base_path": "",
                "clean_pairs": clean_pairs,
                "injected_pairs": injected_pairs,
                "prior_ids": _unique_prior_ids(prior_ids),
            },
            timeout=_INTERNAL_PREFIX_CACHE_HTTP_TIMEOUT_S,
        )
    except Exception as exc:
        _runtime_log("warning", "[PRIORS RUNTIME] prefix store failed", error=str(exc))


def _append_message(existing: str | None, new_message: str | None) -> str | None:
    if not new_message:
        return existing
    if not existing:
        return new_message
    return f"{existing}\n{new_message}"


def _apply_flattened_to_input_dict(
    input_dict: dict[str, Any],
    api_type: str,
    flattened_to_show: dict[str, Any],
) -> dict[str, Any]:
    try:
        cloned_input_dict = deepcopy(input_dict)
    except Exception:
        import dill

        cloned_input_dict = dill.loads(dill.dumps(input_dict))

    complete_json_str, _ = func_kwargs_to_json_str(cloned_input_dict, api_type)
    complete_input = json.loads(complete_json_str)
    restored_to_show = restore_to_show_from_flattened(flattened_to_show)
    merged_raw = merge_filtered_into_raw(complete_input["raw"], restored_to_show)
    wrapped = json.dumps({"raw": merged_raw, "to_show": restored_to_show}, sort_keys=True)
    return json_str_to_original_inp_dict(wrapped, cloned_input_dict, api_type)


def prepare_llm_call_for_priors(input_dict: dict[str, Any], api_type: str) -> PriorPreparationResult:
    run_id = get_run_id()
    complete_json_str, _ = func_kwargs_to_json_str(input_dict, api_type)
    complete_input = json.loads(complete_json_str)
    flattened_to_show = flatten_complete_to_show(complete_input.get("to_show"))
    cleaned_flattened, inherited_prior_ids, warnings = strip_priors_from_flattened(flattened_to_show)

    cleaned_input_dict = _apply_flattened_to_input_dict(input_dict, api_type, cleaned_flattened)
    clean_prompt_pairs = extract_prompt_bearing_pairs(cleaned_flattened, api_type)

    prefix_entry = None
    matched_prefix_len = 0
    working_flattened = dict(cleaned_flattened)
    if run_id and clean_prompt_pairs:
        prefix_entry, matched_prefix_len = _lookup_longest_prefix_cache_hit(run_id, clean_prompt_pairs)
        if prefix_entry is not None:
            working_flattened = replay_injected_prefix(
                cleaned_flattened,
                list(prefix_entry.get("injected_pairs") or []),
            )
            inherited_prior_ids = _unique_prior_ids(
                inherited_prior_ids + list(prefix_entry.get("prior_ids") or [])
            )

    suffix_pairs = clean_prompt_pairs[matched_prefix_len:]
    input_delta_json = json.dumps(suffix_pairs, sort_keys=True)
    retrieval_context = render_retrieval_context(suffix_pairs)

    metadata = PriorRuntimeMetadata(
        status="pending",
        retrieval_context=retrieval_context,
        inherited_prior_ids=inherited_prior_ids,
        injection_anchor={"key": suffix_pairs[0]["key"]} if suffix_pairs else None,
        warning_message="\n".join(warnings) if warnings else None,
    )

    _runtime_log(
        "info",
        "[PRIORS RUNTIME] prepare",
        api_type=api_type,
        run_id=run_id or "(none)",
        inherited_ids=inherited_prior_ids,
        prompt_pairs=len(clean_prompt_pairs),
        prefix_pairs=matched_prefix_len,
        suffix_pairs=len(suffix_pairs),
        context_chars=len(retrieval_context),
    )

    if not clean_prompt_pairs:
        metadata.status = "uninjectable"
        metadata.warning_message = _append_message(
            metadata.warning_message,
            "No prompt-bearing fields found for priors injection.",
        )
        _runtime_log(
            "info",
            "[PRIORS RUNTIME] skipping retrieval",
            status="uninjectable",
            api_type=api_type,
            warning=metadata.warning_message,
        )
        return PriorPreparationResult(
            executed_input_dict=cleaned_input_dict,
            input_delta_json=input_delta_json,
            metadata=metadata,
        )

    executed_flattened = dict(working_flattened)

    if not suffix_pairs:
        metadata.status = "none"
        executed_input_dict = _apply_flattened_to_input_dict(cleaned_input_dict, api_type, executed_flattened)
        _store_prefix_cache_entry(
            run_id,
            clean_prompt_pairs,
            extract_prompt_bearing_pairs(executed_flattened, api_type),
            inherited_prior_ids,
        )
        _runtime_log(
            "info",
            "[PRIORS RUNTIME] skipping retrieval",
            status="none",
            reason="prefix_hit_covers_entire_prompt",
        )
        return PriorPreparationResult(
            executed_input_dict=executed_input_dict,
            input_delta_json=input_delta_json,
            metadata=metadata,
        )

    if not retrieval_context.strip():
        metadata.status = "empty_context"
        executed_input_dict = _apply_flattened_to_input_dict(cleaned_input_dict, api_type, executed_flattened)
        _store_prefix_cache_entry(
            run_id,
            clean_prompt_pairs,
            extract_prompt_bearing_pairs(executed_flattened, api_type),
            inherited_prior_ids,
        )
        _runtime_log(
            "info",
            "[PRIORS RUNTIME] skipping retrieval",
            status="empty_context",
            api_type=api_type,
        )
        return PriorPreparationResult(
            executed_input_dict=executed_input_dict,
            input_delta_json=input_delta_json,
            metadata=metadata,
        )

    if not run_id:
        metadata.status = "unavailable"
        metadata.error_message = "No active run id available for priors retrieval."
        _runtime_log(
            "warning",
            "[PRIORS RUNTIME] skipping retrieval",
            status="unavailable",
            api_type=api_type,
            error=metadata.error_message,
        )
        return PriorPreparationResult(
            executed_input_dict=_apply_flattened_to_input_dict(cleaned_input_dict, api_type, executed_flattened),
            input_delta_json=input_delta_json,
            metadata=metadata,
        )

    try:
        started_at = time.perf_counter()
        _runtime_log(
            "info",
            "[PRIORS RUNTIME] retrieving via internal route",
            run_id=run_id,
            ignore_ids=inherited_prior_ids,
        )
        response = http_post(
            "/internal/priors/retrieve",
            {
                "run_id": run_id,
                "context": retrieval_context,
                "base_path": "",
                "ignore_prior_ids": inherited_prior_ids,
            },
            timeout=_INTERNAL_PRIORS_HTTP_TIMEOUT_S,
        )
        metadata.latency_ms = int((time.perf_counter() - started_at) * 1000)
        metadata.applied_priors = list(response.get("priors") or [])
        metadata.rendered_priors_block = str(response.get("rendered_priors_block") or "")
        metadata.model = response.get("model_used")
        metadata.status = "applied" if metadata.applied_priors else "none"
        _runtime_log(
            "info",
            "[PRIORS RUNTIME] retrieval complete",
            status=metadata.status,
            latency_ms=metadata.latency_ms,
            applied_ids=[prior.get("id") for prior in metadata.applied_priors],
            model=metadata.model,
        )

        executed_input_dict = _apply_flattened_to_input_dict(cleaned_input_dict, api_type, executed_flattened)
        if metadata.rendered_priors_block:
            injected_flattened = inject_priors_block(
                executed_flattened,
                metadata.rendered_priors_block,
                metadata.injection_anchor or {"key": suffix_pairs[0]["key"]},
            )
            executed_flattened = injected_flattened
            executed_input_dict = _apply_flattened_to_input_dict(cleaned_input_dict, api_type, injected_flattened)
        effective_prior_ids = _unique_prior_ids(
            inherited_prior_ids + [
                str(prior.get("id"))
                for prior in metadata.applied_priors
                if isinstance(prior.get("id"), str) and prior.get("id")
            ]
        )
        _store_prefix_cache_entry(
            run_id,
            clean_prompt_pairs,
            extract_prompt_bearing_pairs(executed_flattened, api_type),
            effective_prior_ids,
        )

        return PriorPreparationResult(
            executed_input_dict=executed_input_dict,
            input_delta_json=input_delta_json,
            metadata=metadata,
        )
    except httpx.TimeoutException as exc:
        metadata.status = "timeout"
        metadata.error_message = str(exc)
        _runtime_log("warning", "[PRIORS RUNTIME] retrieval timeout", error=metadata.error_message)
    except httpx.RequestError as exc:
        metadata.status = "unavailable"
        metadata.error_message = str(exc)
        _runtime_log("warning", "[PRIORS RUNTIME] retrieval unavailable", error=metadata.error_message)
    except httpx.HTTPStatusError as exc:
        metadata.error_message = str(exc)
        status_code = exc.response.status_code if exc.response is not None else None
        metadata.status = "unavailable" if status_code in {502, 503, 504} else "error"
        _runtime_log(
            "warning",
            "[PRIORS RUNTIME] retrieval http error",
            status_code=status_code,
            error=metadata.error_message,
        )
    except Exception as exc:
        metadata.status = "error"
        metadata.error_message = str(exc)
        _runtime_log("error", "[PRIORS RUNTIME] retrieval failed unexpectedly", error=metadata.error_message)

    executed_input_dict = _apply_flattened_to_input_dict(cleaned_input_dict, api_type, executed_flattened)
    _store_prefix_cache_entry(
        run_id,
        clean_prompt_pairs,
        extract_prompt_bearing_pairs(executed_flattened, api_type),
        inherited_prior_ids,
    )
    return PriorPreparationResult(
        executed_input_dict=executed_input_dict,
        input_delta_json=input_delta_json,
        metadata=metadata,
    )


def persist_prior_metadata(run_id: str, node_uuid: str, metadata: PriorRuntimeMetadata) -> None:
    DB.upsert_prior_retrieval(
        run_id,
        node_uuid,
        retrieval_context=metadata.retrieval_context,
        inherited_prior_ids=metadata.inherited_prior_ids,
        applied_priors=metadata.applied_priors,
        rendered_priors_block=metadata.rendered_priors_block,
        injection_anchor=metadata.injection_anchor,
        model=metadata.model,
        timeout_ms=metadata.timeout_ms,
        latency_ms=metadata.latency_ms,
        warning_message=metadata.warning_message,
        error_message=metadata.error_message,
    )
    for prior in metadata.applied_priors:
        prior_id = prior.get("id")
        if isinstance(prior_id, str) and prior_id:
            DB.add_prior_applied(prior_id, run_id, node_uuid)


def _priors_request(endpoint: str, payload: dict) -> dict:
    """POST to the priors server and return parsed JSON response."""
    url = f"{PRIORS_SERVER_URL}/api/v1{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def _query_priors(path: Optional[str] = None) -> tuple[List[dict], str]:
    """Fetch all priors from a path and return both rows and injected context."""
    payload = {}
    if path is not None:
        payload["path"] = path
    result = _priors_request("/query/priors", payload)
    return result.get("priors", []), result.get("injected_context", "")


def _retrieve_priors(path: Optional[str], context: str, model: Optional[str] = None) -> List[dict]:
    """Retrieve relevant priors via the LLM-backed retriever."""
    payload = {"context": context}
    if path is not None:
        payload["base_path"] = path
    if model is not None:
        payload["model"] = model
    result = _priors_request("/query/priors/retrieve", payload)
    return result.get("priors", [])


def _format_priors(priors: List[dict]) -> str:
    """Format priors into an injectable context block."""
    if not priors:
        return ""
    blocks = [f"## {prior['name']}\n{prior['content']}" for prior in priors]
    return "<priors>\n" + "\n\n".join(blocks) + "\n</priors>"


def _track_priors(prior_ids: List[str]) -> None:
    """Track which priors were applied to the current run."""
    try:
        from sovara.runner.context_manager import get_run_id

        run_id = get_run_id()
        if run_id:
            from sovara.server.database_manager import DB

            for prior_id in prior_ids:
                DB.add_prior_applied(prior_id, run_id)
            logger.debug(f"Tracked {len(prior_ids)} priors applied to run {run_id[:8]}")
    except Exception as e:
        logger.debug(f"Could not track prior application: {e}")


def inject_priors(
    path: Optional[str] = None,
    context: Optional[str] = None,
    method: str = "retrieve",
    model: Optional[str] = None,
) -> str:
    """
    Retrieve priors from the priors server and return them as injected context.

    Args:
        path: Folder path to retrieve priors from (e.g. 'beaver/retriever/').
        context: Context string for LLM-based retrieval (required when method="retrieve").
        method: "retrieve" (LLM-filtered), "all" (all priors in path), or "none".
        model: Optional retriever model override.

    Returns:
        Formatted priors string, or empty string if unavailable.
    """
    if method == "none":
        return ""

    try:
        if method == "retrieve":
            if context is None:
                raise ValueError("context is required when method='retrieve'")
            priors = _retrieve_priors(path, context, model=model)
            injected_context = _format_priors(priors)
        elif method == "all":
            priors, injected_context = _query_priors(path)
        else:
            raise ValueError(f"Unknown method: {method}")
    except (urllib.error.URLError, ConnectionError) as e:
        logger.warning(f"Priors server unavailable: {e}")
        return ""
    except ValueError:
        raise
    except Exception as e:
        logger.warning(f"Failed to fetch priors: {e}")
        return ""

    prior_ids = [prior.get("id") for prior in priors if prior.get("id")]
    if prior_ids:
        _track_priors(prior_ids)

    return injected_context
