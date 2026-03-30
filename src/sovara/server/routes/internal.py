"""Internal server-only REST endpoints."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from sovara.common.constants import MAIN_SERVER_LOG
from sovara.common.logger import create_file_logger
from sovara.server.llm_backend import StructuredInferenceError, infer_structured_json
from sovara.server.database_manager import DB
from sovara.server.priors_client import PriorsBackendClient, PriorsBackendError

router = APIRouter(prefix="/internal")
main_server_logger = create_file_logger(MAIN_SERVER_LOG)

_ANCHOR_RESOLUTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "anchor_resolution",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "found": {"type": "boolean"},
                "anchor_key": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["found", "anchor_key", "reason"],
            "additionalProperties": False,
        },
    },
}

_ANCHOR_RESOLUTION_SYSTEM_PROMPT = """You choose the exact flattened key where Sovara should prepend a <sovara-priors> block.

Return exactly one anchor_key from the provided candidate keys, or return found=false if none are safe.

Prefer prompt-bearing instruction fields such as:
- body.system
- system
- body.instructions
- instructions
- body.input
- input
- body.messages.0.content
- messages.0.content
- body.input.0.content.0.text
- input.0.content.0.text
- system_instruction.parts.0.text
- systemInstruction.parts.0.text
- contents.0.parts.0.text

Never choose metadata-only fields such as url, model, temperature, role, type, id, path, name, or other transport/config keys.
Choose only from the provided candidate keys. Do not invent keys."""


class InternalInferRequest(BaseModel):
    purpose: str
    model: str
    tier: Literal["cheap", "expensive"] = "expensive"
    messages: list[dict[str, Any]]
    response_format: dict[str, Any] | None = None
    timeout_ms: int | None = None
    repair_attempts: int = Field(default=1, ge=0, le=3)

    model_config = ConfigDict(extra="allow")


class InternalPriorsRetrieveRequest(BaseModel):
    run_id: str
    context: str
    model: str | None = None
    ignore_prior_ids: list[str] = Field(default_factory=list)


class InternalResolveAnchorRequest(BaseModel):
    api_type: str
    available_keys: list[str] = Field(default_factory=list)
    candidate_previews: dict[str, str] = Field(default_factory=dict)


class InternalPrefixCacheLookupRequest(BaseModel):
    run_id: str
    clean_pairs: list[dict[str, str]] = Field(default_factory=list)


class InternalPrefixCacheStoreRequest(BaseModel):
    run_id: str
    clean_pairs: list[dict[str, str]] = Field(default_factory=list)
    injected_pairs: list[dict[str, str]] = Field(default_factory=list)
    prior_ids: list[str] = Field(default_factory=list)


class InternalResolveAnchorResponse(BaseModel):
    found: bool
    anchor_key: str
    reason: str
    model_used: str | None = None
    structured_mode: str | None = None


@router.post("/llm/infer")
def internal_llm_infer(req: InternalInferRequest):
    kwargs = dict(req.model_extra or {})
    if req.timeout_ms is not None:
        kwargs["timeout"] = max(req.timeout_ms / 1000.0, 0.001)

    try:
        return infer_structured_json(
            req.messages,
            req.model,
            tier=req.tier,
            response_format=req.response_format,
            repair_attempts=req.repair_attempts,
            **kwargs,
        )
    except StructuredInferenceError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": str(exc),
                "raw_text": exc.raw_text,
                "structured_mode": exc.structured_mode,
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/priors/retrieve")
def internal_priors_retrieve(req: InternalPriorsRetrieveRequest):
    run = DB.query_one("SELECT user_id, project_id FROM runs WHERE run_id=?", (req.run_id,))
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {req.run_id}")
    if not run["user_id"] or not run["project_id"]:
        raise HTTPException(status_code=400, detail="Run is missing user/project scope for priors retrieval")

    client = PriorsBackendClient(user_id=run["user_id"], project_id=run["project_id"])
    try:
        return client.retrieve_priors(
            {
                "context": req.context,
                "model": req.model,
                "ignore_prior_ids": req.ignore_prior_ids,
            }
        )
    except PriorsBackendError as exc:
        status_code = exc.status_code if 400 <= exc.status_code < 600 else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/priors/prefix-cache/lookup")
def internal_priors_prefix_cache_lookup(req: InternalPrefixCacheLookupRequest):
    run = DB.query_one("SELECT user_id, project_id FROM runs WHERE run_id=?", (req.run_id,))
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {req.run_id}")
    if not run["user_id"] or not run["project_id"]:
        raise HTTPException(status_code=400, detail="Run is missing user/project scope for priors prefix lookup")

    client = PriorsBackendClient(user_id=run["user_id"], project_id=run["project_id"])
    try:
        return client.lookup_prefix_cache(
            {
                "clean_pairs": req.clean_pairs,
            }
        )
    except PriorsBackendError as exc:
        status_code = exc.status_code if 400 <= exc.status_code < 600 else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/priors/prefix-cache/store")
def internal_priors_prefix_cache_store(req: InternalPrefixCacheStoreRequest):
    run = DB.query_one("SELECT user_id, project_id FROM runs WHERE run_id=?", (req.run_id,))
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {req.run_id}")
    if not run["user_id"] or not run["project_id"]:
        raise HTTPException(status_code=400, detail="Run is missing user/project scope for priors prefix store")

    client = PriorsBackendClient(user_id=run["user_id"], project_id=run["project_id"])
    try:
        return client.store_prefix_cache(
            {
                "clean_pairs": req.clean_pairs,
                "injected_pairs": req.injected_pairs,
                "prior_ids": req.prior_ids,
            }
        )
    except PriorsBackendError as exc:
        status_code = exc.status_code if 400 <= exc.status_code < 600 else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/priors/resolve-anchor", response_model=InternalResolveAnchorResponse)
def internal_priors_resolve_anchor(req: InternalResolveAnchorRequest):
    if not req.candidate_previews:
        return InternalResolveAnchorResponse(
            found=False,
            anchor_key="",
            reason="No candidate string keys were provided.",
        )

    main_server_logger.warning(
        "[PRIORS ANCHOR] fallback resolution requested for api_type=%s available_keys=%s",
        req.api_type,
        req.available_keys,
    )

    candidate_lines = "\n".join(
        f"- {key}: {preview}"
        for key, preview in sorted(req.candidate_previews.items())
    )
    available_keys = "\n".join(f"- {key}" for key in req.available_keys)
    result = infer_structured_json(
        [
            {"role": "system", "content": _ANCHOR_RESOLUTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"API type: {req.api_type}\n"
                    "All flattened keys:\n"
                    f"{available_keys or '(none)'}\n\n"
                    "Candidate string keys with previews:\n"
                    f"{candidate_lines}"
                ),
            },
        ],
        "openai/gpt-5.4",
        tier="cheap",
        response_format=_ANCHOR_RESOLUTION_RESPONSE_FORMAT,
        repair_attempts=1,
        timeout=10.0,
    )
    parsed = result["parsed"]
    anchor_key = parsed.get("anchor_key", "").strip()
    found = bool(parsed.get("found")) and bool(anchor_key)

    if found and anchor_key not in req.candidate_previews:
        main_server_logger.warning(
            "[PRIORS ANCHOR] model returned unsupported anchor_key=%s for api_type=%s",
            anchor_key,
            req.api_type,
        )
        return InternalResolveAnchorResponse(
            found=False,
            anchor_key="",
            reason=f"Model selected unsupported anchor key: {anchor_key}",
            model_used=result.get("model_used"),
            structured_mode=result.get("structured_mode"),
        )

    main_server_logger.info(
        "[PRIORS ANCHOR] fallback result for api_type=%s found=%s anchor_key=%s reason=%s",
        req.api_type,
        found,
        anchor_key if found else "",
        str(parsed.get("reason", "")),
    )
    return InternalResolveAnchorResponse(
        found=found,
        anchor_key=anchor_key if found else "",
        reason=str(parsed.get("reason", "")),
        model_used=result.get("model_used"),
        structured_mode=result.get("structured_mode"),
    )
