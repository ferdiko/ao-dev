"""Helpers for resolving priors scope inside the main server."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request

from sovara.common.project import find_project_root, read_project_id
from sovara.common.user import read_user_id
from sovara.server.database_manager import DB


def resolve_active_priors_scope(project_id: str | None = None) -> tuple[str, str]:
    user_id = read_user_id()
    if not user_id:
        raise HTTPException(status_code=404, detail="No user configured.")

    if project_id:
        project = DB.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
        return user_id, project_id

    workspace_root = os.environ.get("SOVARA_WORKSPACE_ROOT") or os.getcwd()
    project_root = find_project_root(workspace_root)
    if project_root:
        return user_id, read_project_id(project_root)

    result = DB.find_project_for_location(user_id, workspace_root)
    if result:
        resolved_project_id, _project_location = result
        return user_id, resolved_project_id

    raise HTTPException(
        status_code=404,
        detail=f"No project configured for workspace '{workspace_root}'.",
    )


def resolve_priors_scope_from_request(
    request: Request,
    *,
    project_id: str | None = None,
) -> tuple[str, str]:
    user_id = request.headers.get("x-sovara-user-id")
    request_project_id = request.headers.get("x-sovara-project-id")
    if user_id and request_project_id:
        return user_id, request_project_id
    return resolve_active_priors_scope(project_id=project_id)
