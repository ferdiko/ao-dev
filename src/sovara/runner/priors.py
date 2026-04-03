"""Runtime priors helpers and the legacy manual priors injection API."""
from dataclasses import dataclass, field
import io
import json
import time
import urllib.error
import urllib.request
from typing import Any, List, Optional

from sovara.common.constants import PRIORS_SERVER_URL
from sovara.common.logger import logger
from sovara.common.utils import http_post
from sovara.runner.context_manager import get_run_id
from sovara.runner.monkey_patching.api_parser import (
    flatten_complete_to_show,
    func_kwargs_to_json_str,
    replace_to_show_in_input_dict,
    restore_complete_to_show_from_flattened,
)
from sovara.runner.priors_pipeline import (
    detect_manual_priors_reason,
    extract_prompt_bearing_pairs,
    inject_priors_block,
    replay_injected_prefix,
    render_retrieval_context,
    strip_priors_from_flattened,
)
from sovara.server.database_manager import DB

_INTERNAL_PRIORS_TIMEOUT_MS = 30000
_INTERNAL_PRIORS_HTTP_TIMEOUT_S = (_INTERNAL_PRIORS_TIMEOUT_MS / 1000.0) + 5.0
_INTERNAL_PREFIX_CACHE_TIMEOUT_MS = 10000
_INTERNAL_PREFIX_CACHE_HTTP_TIMEOUT_S = (_INTERNAL_PREFIX_CACHE_TIMEOUT_MS / 1000.0) + 5.0


@dataclass(slots=True)
class PriorRuntimeMetadata:
    """Priors-sidecar metadata for one prepared LLM call.

    `status` is a coarse runtime/debug label for the preparation outcome.
    `injection_anchor` is the prompt-bearing key where newly retrieved priors
    would be injected for this node's suffix, if any.
    `warning_message` captures non-fatal cleanup/strip warnings.
    `retrieval_context` is the rendered suffix context sent to the retriever.
    `inherited_prior_ids` are priors recovered from stripped manual blocks or
    prefix-cache replay.
    `newly_applied_priors` are only the priors freshly retrieved for this node.
    `rendered_priors_block` is the exact block injected for those fresh priors.
    `model` is the retriever model actually used.
    `timeout_ms` is the fixed internal priors-route timeout.
    `latency_ms` is populated only when a retrieval request is made.
    `error_message` captures fatal retrieval/preparation failures.
    """

    status: str
    injection_anchor: dict[str, Any] | None
    warning_message: str | None
    retrieval_context: str = ""
    inherited_prior_ids: list[str] = field(default_factory=list)
    newly_applied_priors: list[dict[str, Any]] = field(default_factory=list)
    rendered_priors_block: str = ""
    model: str | None = None
    timeout_ms: int = field(default=_INTERNAL_PRIORS_TIMEOUT_MS, init=False)
    latency_ms: int | None = None
    error_message: str | None = None


@dataclass(slots=True)
class PriorPreparationResult:
    """Prepared priors artifacts returned to a transport patch.

    `executed_input_dict` is the final outbound payload that should be sent to
    the provider after stripping, replaying, and injecting priors.
    `prompt_suffix_json` is the JSON-serialized unmatched prompt-bearing suffix
    for this node, which is stored for observability on the captured LLM call.
    `metadata` is the priors retrieval/replay sidecar persisted separately.
    """

    executed_input_dict: dict[str, Any]
    prompt_suffix_json: str
    metadata: PriorRuntimeMetadata


def _runtime_log(level: str, message: str, **details: Any) -> None:
    log_method = getattr(logger, level)
    details = {"source": "automatic", **details}
    if details:
        detail_text = json.dumps(details, sort_keys=True, ensure_ascii=False)
        log_method("%s | %s", message, detail_text)
    else:
        log_method(message)


def _manual_log(level: str, message: str, **details: Any) -> None:
    log_method = getattr(logger, level)
    details = {"source": "manual", **details}
    if details:
        detail_text = json.dumps(details, sort_keys=True, ensure_ascii=False)
        log_method("%s | %s", message, detail_text)
    else:
        log_method(message)


def _httpx_response_detail(exc: Any) -> str | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        payload = response.json()
    except Exception:
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        return None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if detail is not None:
            try:
                return json.dumps(detail, sort_keys=True, ensure_ascii=False)
            except Exception:
                return str(detail)
    try:
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(payload)

def _unique_prior_ids(prior_ids: list[str]) -> list[str]:
    # Preserve first-seen order so replayed/inherited priors stay stable.
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
                "clean_pairs": clean_pairs,
                "injected_pairs": injected_pairs,
                "prior_ids": prior_ids,
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


def prepare_llm_call_for_priors(input_dict: dict[str, Any], api_type: str) -> PriorPreparationResult:
    run_id = get_run_id()
    complete_json_str, _ = func_kwargs_to_json_str(input_dict, api_type)
    complete_input = json.loads(complete_json_str)
    flattened_to_show = flatten_complete_to_show(complete_input.get("to_show"))
    manual_priors_reason = detect_manual_priors_reason(flattened_to_show)
    if manual_priors_reason is not None:
        metadata = PriorRuntimeMetadata(
            status="manual",
            retrieval_context="",
            inherited_prior_ids=[],
            injection_anchor=None,
            warning_message=manual_priors_reason,
        )
        return PriorPreparationResult(
            executed_input_dict=input_dict,
            prompt_suffix_json="[]",
            metadata=metadata,
        )

    cleaned_flattened, inherited_prior_ids, warnings = strip_priors_from_flattened(flattened_to_show)

    cleaned_input_dict = replace_to_show_in_input_dict(
        input_dict,
        api_type,
        restore_complete_to_show_from_flattened(cleaned_flattened),
    )
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
    prompt_suffix_json = json.dumps(suffix_pairs, sort_keys=True)
    retrieval_context = render_retrieval_context(suffix_pairs)

    metadata = PriorRuntimeMetadata(
        status="pending",
        retrieval_context=retrieval_context,
        inherited_prior_ids=inherited_prior_ids,
        injection_anchor={"key": suffix_pairs[0]["key"]} if suffix_pairs else None,
        warning_message="\n".join(warnings) if warnings else None,
    )

    if not clean_prompt_pairs:
        metadata.status = "uninjectable"
        metadata.warning_message = _append_message(
            metadata.warning_message,
            "No prompt-bearing fields found for priors injection.",
        )
        return PriorPreparationResult(
            executed_input_dict=cleaned_input_dict,
            prompt_suffix_json=prompt_suffix_json,
            metadata=metadata,
        )

    executed_flattened = dict(working_flattened)

    if not suffix_pairs:
        metadata.status = "none"
        executed_input_dict = replace_to_show_in_input_dict(
            cleaned_input_dict,
            api_type,
            restore_complete_to_show_from_flattened(executed_flattened),
        )
        return PriorPreparationResult(
            executed_input_dict=executed_input_dict,
            prompt_suffix_json=prompt_suffix_json,
            metadata=metadata,
        )

    if not retrieval_context.strip():
        metadata.status = "empty_context"
        executed_input_dict = replace_to_show_in_input_dict(
            cleaned_input_dict,
            api_type,
            restore_complete_to_show_from_flattened(executed_flattened),
        )
        return PriorPreparationResult(
            executed_input_dict=executed_input_dict,
            prompt_suffix_json=prompt_suffix_json,
            metadata=metadata,
        )

    if not run_id:
        metadata.status = "unavailable"
        metadata.error_message = "No active run id available for priors retrieval."
        _runtime_log("warning", "[PRIORS RUNTIME] retrieval unavailable", error=metadata.error_message)
        return PriorPreparationResult(
            executed_input_dict=replace_to_show_in_input_dict(
                cleaned_input_dict,
                api_type,
                restore_complete_to_show_from_flattened(executed_flattened),
            ),
            prompt_suffix_json=prompt_suffix_json,
            metadata=metadata,
        )

    import httpx

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
                "ignore_prior_ids": inherited_prior_ids,
            },
            timeout=_INTERNAL_PRIORS_HTTP_TIMEOUT_S,
        )
        metadata.latency_ms = int((time.perf_counter() - started_at) * 1000)
        metadata.newly_applied_priors = list(response.get("priors") or [])
        metadata.rendered_priors_block = str(response.get("rendered_priors_block") or "")
        metadata.model = response.get("model_used")
        metadata.status = "applied" if metadata.newly_applied_priors else "none"
        _runtime_log(
            "info",
            "[PRIORS RUNTIME] retrieval complete",
            status=metadata.status,
            latency_ms=metadata.latency_ms,
            applied_ids=[prior.get("id") for prior in metadata.newly_applied_priors],
            model=metadata.model,
        )

        executed_input_dict = replace_to_show_in_input_dict(
            cleaned_input_dict,
            api_type,
            restore_complete_to_show_from_flattened(executed_flattened),
        )
        if metadata.rendered_priors_block:
            injected_flattened = inject_priors_block(
                executed_flattened,
                metadata.rendered_priors_block,
                metadata.injection_anchor or {"key": suffix_pairs[0]["key"]},
            )
            executed_flattened = injected_flattened
            executed_input_dict = replace_to_show_in_input_dict(
                cleaned_input_dict,
                api_type,
                restore_complete_to_show_from_flattened(injected_flattened),
            )
        effective_prior_ids = _unique_prior_ids(
            inherited_prior_ids + [
                str(prior.get("id"))
                for prior in metadata.newly_applied_priors
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
            prompt_suffix_json=prompt_suffix_json,
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
        response_detail = _httpx_response_detail(exc)
        _runtime_log(
            "warning",
            "[PRIORS RUNTIME] retrieval http error",
            status_code=status_code,
            error=metadata.error_message,
            detail=response_detail,
        )
    except Exception as exc:
        metadata.status = "error"
        metadata.error_message = str(exc)
        _runtime_log("error", "[PRIORS RUNTIME] retrieval failed unexpectedly", error=metadata.error_message)

    executed_input_dict = replace_to_show_in_input_dict(
        cleaned_input_dict,
        api_type,
        restore_complete_to_show_from_flattened(executed_flattened),
    )
    return PriorPreparationResult(
        executed_input_dict=executed_input_dict,
        prompt_suffix_json=prompt_suffix_json,
        metadata=metadata,
    )


def persist_prior_metadata(run_id: str, node_uuid: str, metadata: PriorRuntimeMetadata) -> None:
    DB.upsert_prior_retrieval(
        run_id,
        node_uuid,
        retrieval_context=metadata.retrieval_context,
        inherited_prior_ids=metadata.inherited_prior_ids,
        applied_priors=metadata.newly_applied_priors,
        rendered_priors_block=metadata.rendered_priors_block,
        injection_anchor=metadata.injection_anchor,
        model=metadata.model,
        timeout_ms=metadata.timeout_ms,
        latency_ms=metadata.latency_ms,
        warning_message=metadata.warning_message,
        error_message=metadata.error_message,
    )
    for prior in metadata.newly_applied_priors:
        prior_id = prior.get("id")
        if isinstance(prior_id, str) and prior_id:
            DB.add_prior_applied(prior_id, run_id, node_uuid)


def _priors_request(endpoint: str, payload: dict) -> dict:
    """POST to the priors server and return parsed JSON response."""
    url = f"{PRIORS_SERVER_URL}/api/v1{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    run_id = get_run_id()
    if run_id:
        run = DB.query_one("SELECT user_id, project_id FROM runs WHERE run_id=?", (run_id,))
        if run is not None:
            user_id = run.get("user_id")
            project_id = run.get("project_id")
            if user_id:
                headers["x-sovara-user-id"] = str(user_id)
            if project_id:
                headers["x-sovara-project-id"] = str(project_id)

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def _query_priors(path: Optional[str] = None) -> tuple[List[dict], str]:
    """Fetch all priors from a path and return both rows and injected context."""
    run_id = get_run_id()
    if run_id:
        result = http_post(
            "/internal/priors/query",
            {
                "run_id": run_id,
                "path": path,
            },
            timeout=_INTERNAL_PRIORS_HTTP_TIMEOUT_S,
        )
    else:
        payload = {}
        if path is not None:
            payload["path"] = path
        result = _priors_request("/query/priors", payload)
    return result.get("priors", []), result.get("injected_context", "")


def _retrieve_priors(path: Optional[str], context: str) -> List[dict]:
    """Retrieve relevant priors via the LLM-backed retriever."""
    run_id = get_run_id()
    if run_id:
        result = http_post(
            "/internal/priors/retrieve",
            {
                "run_id": run_id,
                "context": context,
                "base_path": path,
                "ignore_prior_ids": [],
            },
            timeout=_INTERNAL_PRIORS_HTTP_TIMEOUT_S,
        )
    else:
        payload = {"context": context}
        if path is not None:
            payload["base_path"] = path
        result = _priors_request("/priors/retrieve", payload)
    return result.get("priors", [])


def _format_priors(priors: List[dict]) -> str:
    """Format priors into an injectable context block."""
    if not priors:
        return ""
    manifest = {
        "manual": True,
        "priors": [
            {"id": prior["id"]}
            for prior in priors
            if prior.get("id")
        ],
    }
    blocks = [f"## {prior['name']}\n{prior['content']}" for prior in priors]
    return (
        "<sovara-priors>\n"
        f"<!-- {json.dumps(manifest, separators=(',', ':'))} -->\n"
        + "\n\n".join(blocks)
        + "\n</sovara-priors>"
    )


def _stringify_context(context: Any) -> str:
    if isinstance(context, str):
        return context
    try:
        return json.dumps(context, indent=2, ensure_ascii=False)
    except TypeError:
        return str(context)


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


def _http_error_detail(exc: urllib.error.HTTPError) -> str | None:
    if exc.fp is None:
        return None
    raw: bytes | None = None
    try:
        raw = exc.fp.read()
    except Exception:
        return None
    finally:
        try:
            exc.fp = io.BytesIO(raw if isinstance(raw, bytes) else b"")
        except Exception:
            pass

    if not isinstance(raw, bytes) or not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        text = raw.decode("utf-8", errors="ignore").strip()
        return text or None

    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return None


def inject_priors(
    path: Optional[str] = None,
    context: Any = None,
    method: str = "retrieve",
) -> str:
    """
    Retrieve priors from the priors server and return them as injected context.

    Args:
        path: Folder path to retrieve priors from (e.g. 'beaver/retriever/').
        context: Retrieval context. Supports str, dict, list, or other JSON-serializable
            values, which are stringified before retrieval.
        method: "retrieve" (LLM-filtered), "all" (all priors in path), or "none".
    Returns:
        Formatted priors string, or empty string if the priors server is unavailable.

    Raises:
        ValueError: When the requested priors folder path is invalid for the current scope.
        RuntimeError: When the priors request fails with a non-recoverable HTTP error.
    """
    path_label = path or "<root>"
    if method == "none":
        return ""

    context_text: str | None = None
    if method == "retrieve":
        if context is None:
            raise ValueError("context is required when method='retrieve'")
        context_text = _stringify_context(context)
    _manual_log(
        "info",
        "[PRIORS MANUAL] fetching",
        path=path_label,
        method=method,
        context_chars=len(context_text) if context_text is not None else 0,
    )

    try:
        if method == "retrieve":
            priors = _retrieve_priors(path, context_text or "")
            injected_context = _format_priors(priors)
        elif method == "all":
            priors, _unused_injected_context = _query_priors(path)
            injected_context = _format_priors(priors)
        else:
            raise ValueError(f"Unknown method: {method}")
    except urllib.error.HTTPError as e:
        detail = _http_error_detail(e) or e.reason
        _manual_log(
            "warning",
            "[PRIORS MANUAL] fetch http error",
            path=path_label,
            method=method,
            status_code=e.code,
            detail=detail,
        )
        if e.code == 404 and path:
            raise ValueError(
                f"inject_priors(path={path!r}, method={method!r}) failed because the prior folder "
                f"{path!r} does not exist in the current SovaraDB project scope. "
                f"Fix the path or create that folder in SovaraDB and retry. "
                f"Backend detail: {detail}"
            ) from e
        raise RuntimeError(
            f"inject_priors(path={path!r}, method={method!r}) failed with HTTP {e.code}: {detail}"
        ) from e
    except (urllib.error.URLError, ConnectionError) as e:
        _manual_log(
            "warning",
            "[PRIORS MANUAL] fetch unavailable",
            path=path_label,
            method=method,
            error=str(e),
        )
        return ""
    except ValueError:
        raise
    except Exception as e:
        _manual_log(
            "warning",
            "[PRIORS MANUAL] fetch failed",
            path=path_label,
            method=method,
            error=str(e),
        )
        return ""

    prior_ids = [prior.get("id") for prior in priors if prior.get("id")]
    if prior_ids:
        _track_priors(prior_ids)
    _manual_log(
        "info",
        "[PRIORS MANUAL] fetch complete",
        path=path_label,
        method=method,
        status="applied" if prior_ids else "none",
        applied_ids=prior_ids,
    )

    return injected_context
