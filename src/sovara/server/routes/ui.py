"""UI REST endpoints -- called by VS Code extension and web app."""

import os
import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sovara.common.constants import PRIORS_SERVER_URL, SOVARA_CONFIG
from sovara.common.project import delete_project_configs
from sovara.common.user import read_user_id, write_user_id
from sovara.server.app import get_state
from sovara.server.database_manager import DB, BadRequestError
from sovara.server.llm_settings import normalize_user_llm_settings_row
from sovara.server.state import ServerState

from . import ui_projects as _ui_projects
from . import ui_runs as _ui_runs
from . import ui_trace_chat as _ui_trace_chat

router = APIRouter(prefix="/ui")


def _notify_user_state_changed(state: ServerState) -> None:
    """Broadcast all UI invalidations caused by a local-user identity change."""
    state.notify_user_changed()
    state.notify_project_list_changed()
    state.notify_run_list_changed()


def _serialize_user(row) -> dict:
    return {
        "user_id": row["user_id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "llm_settings": normalize_user_llm_settings_row(row),
    }


def _normalize_user_llm_settings_request(req) -> dict:
    normalized = {}
    for tier in ("primary", "helper"):
        tier_req = getattr(req, tier)
        model_name = tier_req.model_name.strip()
        if not model_name:
            raise BadRequestError(f"{tier.title()} model name is required.")

        api_base = tier_req.api_base.strip() if isinstance(tier_req.api_base, str) else None
        if tier_req.provider == "hosted_vllm" and not api_base:
            raise BadRequestError(f"{tier.title()} API base is required for hosted vLLM.")
        if tier_req.provider != "hosted_vllm":
            api_base = None

        normalized[tier] = {
            "provider": tier_req.provider,
            "model_name": model_name,
            "api_base": api_base,
        }
    return normalized


class SetupUserRequest(BaseModel):
    full_name: str
    email: str


class UpdateUserRequest(BaseModel):
    full_name: str
    email: str


class UpdateUserLlmTierSettingsRequest(BaseModel):
    provider: Literal["anthropic", "together", "hosted_vllm"]
    model_name: str
    api_base: str | None = None


class UpdateUserLlmSettingsRequest(BaseModel):
    primary: UpdateUserLlmTierSettingsRequest
    helper: UpdateUserLlmTierSettingsRequest


class DeleteUserRequest(BaseModel):
    confirmation_name: str


@router.get("/config")
def get_ui_config():
    """Return static UI bootstrap configuration."""
    return {
        "config_path": SOVARA_CONFIG,
        "priors_url": PRIORS_SERVER_URL,
    }


@router.get("/user")
def get_user():
    """Get the local user's info."""
    user_id = read_user_id()
    if not user_id:
        return {"user": None}
    row = DB.get_user(user_id)
    if not row:
        return {"user": None}
    return {"user": _serialize_user(row)}


@router.post("/setup-user")
def setup_user(req: SetupUserRequest, state: ServerState = Depends(get_state)):
    """Create or update the local user profile."""
    if not req.full_name.strip():
        return JSONResponse(status_code=400, content={"error": "Full name is required."})
    if not req.email.strip():
        return JSONResponse(status_code=400, content={"error": "Email is required."})

    user_id = read_user_id()
    if not user_id:
        user_id = str(uuid.uuid4())
        write_user_id(user_id)

    DB.upsert_user(user_id, req.full_name.strip(), req.email.strip())
    row = DB.get_user(user_id)
    _notify_user_state_changed(state)
    return {"user": _serialize_user(row)}


@router.post("/update-user")
def update_user(req: UpdateUserRequest, state: ServerState = Depends(get_state)):
    """Update the local user's profile."""
    user_id = read_user_id()
    if not user_id:
        return JSONResponse(status_code=404, content={"error": "No user configured."})
    if not req.full_name.strip():
        return JSONResponse(status_code=400, content={"error": "Full name is required."})
    if not req.email.strip():
        return JSONResponse(status_code=400, content={"error": "Email is required."})
    DB.upsert_user(user_id, req.full_name.strip(), req.email.strip())
    row = DB.get_user(user_id)
    _notify_user_state_changed(state)
    return {"user": _serialize_user(row)}


@router.post("/update-user-llm-settings")
def update_user_llm_settings(req: UpdateUserLlmSettingsRequest, state: ServerState = Depends(get_state)):
    """Update the local user's persisted trace-chat model settings."""
    user_id = read_user_id()
    if not user_id:
        return JSONResponse(status_code=404, content={"error": "No user configured."})
    row = DB.get_user(user_id)
    if not row:
        return JSONResponse(status_code=404, content={"error": "User not found."})

    try:
        normalized = _normalize_user_llm_settings_request(req)
    except BadRequestError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    DB.update_user_llm_settings(user_id, normalized)
    updated_row = DB.get_user(user_id)
    _notify_user_state_changed(state)
    return {"user": _serialize_user(updated_row)}


@router.post("/delete-user")
def delete_user(req: DeleteUserRequest, state: ServerState = Depends(get_state)):
    """Delete the local user and all associated data."""
    user_id = read_user_id()
    if not user_id:
        return JSONResponse(status_code=404, content={"error": "No user configured."})
    row = DB.get_user(user_id)
    if not row:
        return JSONResponse(status_code=404, content={"error": "User not found."})
    if req.confirmation_name != row["full_name"]:
        return JSONResponse(status_code=400, content={"error": "Name does not match."})
    delete_project_configs(DB.get_user_project_locations(user_id))
    DB.delete_user(user_id)

    from sovara.common.constants import USER_ID_PATH

    if os.path.isfile(USER_ID_PATH):
        os.remove(USER_ID_PATH)
    _notify_user_state_changed(state)
    return {"ok": True}


@router.post("/refresh-user")
def refresh_user(state: ServerState = Depends(get_state)):
    """Broadcast that the local user identity changed outside the server process."""
    _notify_user_state_changed(state)
    return {"ok": True}

router.include_router(_ui_projects.router)
router.include_router(_ui_runs.router)
router.include_router(_ui_trace_chat.router)

CreateProjectRequest = _ui_projects.CreateProjectRequest
UpdateProjectLocationRequest = _ui_projects.UpdateProjectLocationRequest
DeleteProjectLocationRequest = _ui_projects.DeleteProjectLocationRequest
UpdateProjectRequest = _ui_projects.UpdateProjectRequest
DeleteProjectRequest = _ui_projects.DeleteProjectRequest
CreateProjectTagRequest = _ui_projects.CreateProjectTagRequest
DeleteProjectTagRequest = _ui_projects.DeleteProjectTagRequest
pick_directory = _ui_projects.pick_directory
create_project = _ui_projects.create_project
update_project_location = _ui_projects.update_project_location
update_project = _ui_projects.update_project
delete_project_location = _ui_projects.delete_project_location
delete_project = _ui_projects.delete_project
get_projects = _ui_projects.get_projects
get_project = _ui_projects.get_project
get_project_tags = _ui_projects.get_project_tags
create_project_tag = _ui_projects.create_project_tag
delete_project_tag = _ui_projects.delete_project_tag

EditInputRequest = _ui_runs.EditInputRequest
EditOutputRequest = _ui_runs.EditOutputRequest
UpdateNodeRequest = _ui_runs.UpdateNodeRequest
UpdateRunNameRequest = _ui_runs.UpdateRunNameRequest
UpdateThumbLabelRequest = _ui_runs.UpdateThumbLabelRequest
UpdateNotesRequest = _ui_runs.UpdateNotesRequest
RestartRequest = _ui_runs.RestartRequest
EraseRequest = _ui_runs.EraseRequest
DeleteRunsRequest = _ui_runs.DeleteRunsRequest
UpdateRunTagsRequest = _ui_runs.UpdateRunTagsRequest
PrepareEditRerunRequest = _ui_runs.PrepareEditRerunRequest
delete_runs = _ui_runs.delete_runs
get_project_runs = _ui_runs.get_project_runs
get_graph = _ui_runs.get_graph
probe_run = _ui_runs.probe_run
get_runs = _ui_runs.get_runs
get_more_runs = _ui_runs.get_more_runs
get_run_detail = _ui_runs.get_run_detail
get_priors_applied = _ui_runs.get_priors_applied
get_runs_for_prior = _ui_runs.get_runs_for_prior
edit_input = _ui_runs.edit_input
edit_output = _ui_runs.edit_output
update_node = _ui_runs.update_node
update_run_name = _ui_runs.update_run_name
update_thumb_label = _ui_runs.update_thumb_label
update_run_tags = _ui_runs.update_run_tags
update_notes = _ui_runs.update_notes
restart = _ui_runs.restart
prepare_run_edit_rerun = _ui_runs.prepare_run_edit_rerun
erase = _ui_runs.erase
shutdown = _ui_runs.shutdown
clear = _ui_runs.clear

PersistedTraceChatMessage = _ui_trace_chat.PersistedTraceChatMessage
ChatMessageRequest = _ui_trace_chat.ChatMessageRequest
PersistedTraceChatHistoryRequest = _ui_trace_chat.PersistedTraceChatHistoryRequest
get_trace_chat_history = _ui_trace_chat.get_trace_chat_history
update_trace_chat_history = _ui_trace_chat.update_trace_chat_history
clear_trace_chat_history = _ui_trace_chat.clear_trace_chat_history
prefetch_trace = _ui_trace_chat.prefetch_trace
chat = _ui_trace_chat.chat
abort_trace_chat = _ui_trace_chat.abort_trace_chat
