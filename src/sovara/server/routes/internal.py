"""Internal server-only REST endpoints."""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sovara.common.constants import MAIN_SERVER_LOG
from sovara.common.logger import create_file_logger
from sovara.server.database_manager import DB
from sovara.server.priors_backend.routes import (
    lookup_prefix_cache_for_scope,
    query_priors_for_scope,
    retrieve_priors_for_scope,
    store_prefix_cache_for_scope,
)

router = APIRouter(prefix="/internal")
main_server_logger = create_file_logger(MAIN_SERVER_LOG)


class InternalPriorsRetrieveRequest(BaseModel):
    run_id: str
    context: str
    base_path: str | None = None
    ignore_prior_ids: list[str] = Field(default_factory=list)


class InternalPriorsQueryRequest(BaseModel):
    run_id: str
    path: str | None = None


class InternalPrefixCacheLookupRequest(BaseModel):
    run_id: str
    clean_pairs: list[dict[str, str]] = Field(default_factory=list)


class InternalPrefixCacheStoreRequest(BaseModel):
    run_id: str
    clean_pairs: list[dict[str, str]] = Field(default_factory=list)
    injected_pairs: list[dict[str, str]] = Field(default_factory=list)
    prior_ids: list[str] = Field(default_factory=list)


async def _get_run_scope_or_raise(run_id: str) -> tuple[str, str]:
    run = await asyncio.to_thread(
        DB.query_one,
        "SELECT user_id, project_id FROM runs WHERE run_id=?",
        (run_id,),
    )
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    if not run["user_id"] or not run["project_id"]:
        raise HTTPException(status_code=400, detail="Run is missing user/project scope for priors access")
    return str(run["user_id"]), str(run["project_id"])

@router.post("/priors/retrieve")
async def internal_priors_retrieve(req: InternalPriorsRetrieveRequest):
    base_path_label = req.base_path if req.base_path is not None else "<root>"
    user_id, project_id = await _get_run_scope_or_raise(req.run_id)

    try:
        response = await retrieve_priors_for_scope(
            user_id=user_id,
            project_id=project_id,
            context=req.context,
            base_path=req.base_path or "",
            ignore_prior_ids=req.ignore_prior_ids,
        )
        return response
    except HTTPException as exc:
        main_server_logger.warning(
            "[INTERNAL PRIORS] retrieve failed run_id=%s base_path=%s status_code=%s detail=%s",
            req.run_id,
            base_path_label,
            exc.status_code,
            exc.detail,
        )
        raise
    except Exception as exc:
        main_server_logger.exception(
            "[INTERNAL PRIORS] retrieve crashed run_id=%s base_path=%s",
            req.run_id,
            base_path_label,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/priors/query")
def internal_priors_query(req: InternalPriorsQueryRequest):
    run = DB.query_one("SELECT user_id, project_id FROM runs WHERE run_id=?", (req.run_id,))
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {req.run_id}")
    if not run["user_id"] or not run["project_id"]:
        raise HTTPException(status_code=400, detail="Run is missing user/project scope for priors query")

    return query_priors_for_scope(
        user_id=run["user_id"],
        project_id=run["project_id"],
        path=req.path,
    )


@router.post("/priors/prefix-cache/lookup")
async def internal_priors_prefix_cache_lookup(req: InternalPrefixCacheLookupRequest):
    user_id, project_id = await _get_run_scope_or_raise(req.run_id)
    return await asyncio.to_thread(
        lookup_prefix_cache_for_scope,
        user_id=user_id,
        project_id=project_id,
        clean_pairs=req.clean_pairs,
    )


@router.post("/priors/prefix-cache/store")
async def internal_priors_prefix_cache_store(req: InternalPrefixCacheStoreRequest):
    user_id, project_id = await _get_run_scope_or_raise(req.run_id)
    return await asyncio.to_thread(
        store_prefix_cache_for_scope,
        user_id=user_id,
        project_id=project_id,
        clean_pairs=req.clean_pairs,
        injected_pairs=req.injected_pairs,
        prior_ids=req.prior_ids,
    )
