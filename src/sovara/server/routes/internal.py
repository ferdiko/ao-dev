"""Internal server-only REST endpoints."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from sovara.server.llm_backend import StructuredInferenceError, infer_structured_json
from sovara.server.database_manager import DB
from sovara.server.priors_client import PriorsBackendClient, PriorsBackendError

router = APIRouter(prefix="/internal")


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
    base_path: str = ""
    model: str | None = None
    ignore_prior_ids: list[str] = Field(default_factory=list)


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
                "base_path": req.base_path,
                "model": req.model,
                "ignore_prior_ids": req.ignore_prior_ids,
            }
        )
    except PriorsBackendError as exc:
        status_code = exc.status_code if 400 <= exc.status_code < 600 else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
