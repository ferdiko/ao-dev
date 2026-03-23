"""Runner REST endpoints -- called by ao-record via HTTP POST."""

import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional

from ao.server.app import get_state
from ao.server.state import ServerState, Session, logger
from ao.server.database_manager import DB
from ao.server.handlers.runner_handlers import (
    handle_add_node,
    handle_deregister_message,
    handle_update_command,
    handle_log,
)

router = APIRouter(prefix="/runner")


# ============================================================
# Request models
# ============================================================

class RegisterRequest(BaseModel):
    cwd: str
    command: Optional[str] = None
    environment: dict = Field(default_factory=dict)
    name: Optional[str] = None
    prev_session_id: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = ""
    project_description: Optional[str] = ""
    project_root: Optional[str] = None
    user_id: Optional[str] = None
    user_full_name: Optional[str] = ""
    user_email: Optional[str] = ""


class AddNodeRequest(BaseModel):
    session_id: str
    node: dict
    incoming_edges: list = Field(default_factory=list)


class SubrunRequest(BaseModel):
    name: str
    parent_session_id: str
    cwd: str
    command: Optional[str] = None
    environment: dict = Field(default_factory=dict)
    prev_session_id: Optional[str] = None


class DeregisterRequest(BaseModel):
    session_id: str


class UpdateCommandRequest(BaseModel):
    session_id: str
    command: str


class LogRequest(BaseModel):
    session_id: str
    success: Optional[bool] = None
    entry: Optional[str] = None


# ============================================================
# Endpoints
# ============================================================

@router.post("/register")
def register(req: RegisterRequest, state: ServerState = Depends(get_state)):
    state.touch_activity()

    # Upsert user
    if req.user_id:
        DB.upsert_user(req.user_id, req.user_full_name, req.user_email)

    # Upsert project
    if req.project_id:
        DB.upsert_project(req.project_id, req.project_name, req.project_description)
        DB.update_project_last_run_at(req.project_id)
        state.notify_project_list_changed()

    # Determine session_id
    if req.prev_session_id:
        session_id = req.prev_session_id
    else:
        session_id = str(uuid.uuid4())
        timestamp = datetime.utcnow()
        name = req.name
        if not name:
            run_index = DB.get_next_run_index(project_id=req.project_id)
            name = f"Run {run_index}"
        DB.add_experiment(
            session_id, name, timestamp, req.cwd, req.command,
            req.environment, project_id=req.project_id, user_id=req.user_id,
        )
        # Request async git versioning
        if req.project_id and req.project_root:
            state.request_git_version(session_id, req.project_id, req.project_root)

    # Create/update session
    with state.lock:
        if session_id not in state.sessions:
            session = Session(
                session_id, project_id=req.project_id, project_root=req.project_root,
            )
            state.sessions[session_id] = session
        else:
            session = state.sessions[session_id]
    session.status = "running"

    # Create SSE queue for this runner
    state.runner_event_queues[session_id] = asyncio.Queue()

    state.notify_experiment_list_changed()
    return {"session_id": session_id}


@router.post("/add-node")
def add_node(req: AddNodeRequest, state: ServerState = Depends(get_state)):
    state.touch_activity()
    msg = {"session_id": req.session_id, "node": req.node, "incoming_edges": req.incoming_edges}
    handle_add_node(state, msg)
    # Schedule graph update and color preview broadcasts
    if req.session_id in state.session_graphs:
        graph = state.session_graphs[req.session_id]
        node_colors = [n["border_color"] for n in graph.get("nodes", [])]
        color_preview = node_colors[-6:]
        state.schedule_broadcast(
            {"type": "color_preview_update", "session_id": req.session_id, "color_preview": color_preview}
        )
    state.schedule_graph_update(req.session_id)
    return {"ok": True}


@router.post("/subrun")
def subrun(req: SubrunRequest, state: ServerState = Depends(get_state)):
    state.touch_activity()

    # Inherit project info from parent session
    parent_session = state.sessions.get(req.parent_session_id)
    project_id = parent_session.project_id if parent_session else None
    project_root = parent_session.project_root if parent_session else None

    if req.prev_session_id:
        session_id = req.prev_session_id
    else:
        session_id = str(uuid.uuid4())
        timestamp = datetime.utcnow()
        name = req.name
        if not name:
            run_index = DB.get_next_run_index(project_id=project_id)
            name = f"Run {run_index}"
        DB.add_experiment(
            session_id, name, timestamp, req.cwd, req.command,
            req.environment, req.parent_session_id, None,
            project_id=project_id,
        )
        # Request async git versioning
        if project_id and project_root:
            state.request_git_version(session_id, project_id, project_root)

    # Create session
    with state.lock:
        if session_id not in state.sessions:
            state.sessions[session_id] = Session(
                session_id, project_id=project_id, project_root=project_root,
            )
        session = state.sessions[session_id]
    session.status = "running"
    state.notify_experiment_list_changed()

    return {"session_id": session_id}


@router.post("/deregister")
def deregister(req: DeregisterRequest, state: ServerState = Depends(get_state)):
    state.touch_activity()
    handle_deregister_message(state, {"session_id": req.session_id})
    # Clean up SSE queue
    state.runner_event_queues.pop(req.session_id, None)
    return {"ok": True}


@router.post("/update-command")
def update_command(req: UpdateCommandRequest, state: ServerState = Depends(get_state)):
    state.touch_activity()
    handle_update_command(state, {"session_id": req.session_id, "command": req.command})
    return {"ok": True}


@router.post("/log")
def log_message(req: LogRequest, state: ServerState = Depends(get_state)):
    state.touch_activity()
    handle_log(state, {"session_id": req.session_id, "success": req.success, "entry": req.entry})
    return {"ok": True}
