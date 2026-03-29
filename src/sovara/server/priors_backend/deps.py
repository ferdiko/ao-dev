"""Shared dependencies for priors backend routes."""

from fastapi import HTTPException, Request

from sovara.server.priors_backend.storage import PriorStore


def get_scope_from_request(request: Request) -> tuple[str, str]:
    state = request.scope.get("state")
    if isinstance(state, dict):
        user_id = state.get("user_id")
        project_id = state.get("project_id")
    else:
        user_id = getattr(state, "user_id", None) if state is not None else None
        project_id = getattr(state, "project_id", None) if state is not None else None
    if not user_id or not project_id:
        raise HTTPException(status_code=400, detail="Missing priors scope")
    return user_id, project_id


def get_prior_store(request: Request) -> PriorStore:
    user_id, project_id = get_scope_from_request(request)
    return PriorStore(user_id, project_id)
