"""Runner REST endpoints -- called by so-record via HTTP POST."""

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional

from sovara.server.app import get_state
from sovara.server.state import ServerState, logger
from sovara.server.database import DB
from sovara.common.custom_metrics import MetricsPayload
from sovara.server.handlers.runner_handlers import (
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
    prev_run_id: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = ""
    project_description: Optional[str] = ""
    project_root: Optional[str] = None
    user_id: Optional[str] = None
    user_full_name: Optional[str] = ""
    user_email: Optional[str] = ""


class IncomingNodeRequest(BaseModel):
    uuid: str
    input: str
    output: str
    label: str
    border_color: str
    stack_trace: Optional[str] = None
    model: Optional[str] = None
    attachments: list[str] = Field(default_factory=list)


class AddNodeRequest(BaseModel):
    run_id: str
    node: IncomingNodeRequest
    incoming_edges: list = Field(default_factory=list)


class SubrunRequest(BaseModel):
    name: str
    parent_run_id: str
    cwd: str
    command: Optional[str] = None
    environment: dict = Field(default_factory=dict)
    prev_run_id: Optional[str] = None


class DeregisterRequest(BaseModel):
    run_id: str


class UpdateCommandRequest(BaseModel):
    run_id: str
    command: str


class LogRequest(MetricsPayload):
    run_id: str


# ============================================================
# Endpoints
# ============================================================

@router.post("/register")
def register(req: RegisterRequest, state: ServerState = Depends(get_state)):
    state.touch_activity()

    # Upsert user
    if req.user_id:
        DB.upsert_user(req.user_id, req.user_full_name, req.user_email)
        state.notify_user_changed()

    # Upsert project
    if req.project_id:
        DB.upsert_project(req.project_id, req.project_name, req.project_description)
        DB.update_project_last_run_at(req.project_id)
        state.notify_project_list_changed()

    # Determine run_id
    if req.prev_run_id:
        run_id = req.prev_run_id
    else:
        run_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)
        name = req.name
        if not name:
            run_index = DB.get_next_run_index(project_id=req.project_id)
            name = f"Run {run_index}"
        DB.add_run(
            run_id, name, timestamp, req.cwd, req.command,
            req.environment, project_id=req.project_id, user_id=req.user_id,
        )
        # Request async git versioning
        if req.project_id and req.project_root:
            state.request_git_version(run_id, req.project_id, req.project_root)

    state.start_run_attempt(
        run_id,
        project_id=req.project_id,
        project_root=req.project_root,
        reset_runner_connection=True,
    )

    # Create SSE queue for this runner
    state.runner_event_queues[run_id] = asyncio.Queue()

    state.notify_run_list_changed()
    return {"run_id": run_id}


@router.post("/add-node")
def add_node(req: AddNodeRequest, state: ServerState = Depends(get_state)):
    state.touch_activity()
    msg = {
        "run_id": req.run_id,
        "node": req.node.model_dump(),
        "incoming_edges": req.incoming_edges,
    }
    handle_add_node(state, msg)
    # Schedule graph update and color preview broadcasts
    if req.run_id in state.run_graphs:
        graph = state.run_graphs[req.run_id]
        node_colors = [n.border_color for n in graph.nodes]
        color_preview = node_colors[-6:]
        state.schedule_broadcast(
            {"type": "color_preview_update", "run_id": req.run_id, "color_preview": color_preview}
        )
    state.schedule_graph_update(req.run_id)
    return {"ok": True}


@router.post("/subrun")
def subrun(req: SubrunRequest, state: ServerState = Depends(get_state)):
    state.touch_activity()

    # Inherit project info from the parent run
    parent_run = state.runs.get(req.parent_run_id)
    project_id = parent_run.project_id if parent_run else None
    project_root = parent_run.project_root if parent_run else None

    if req.prev_run_id:
        run_id = req.prev_run_id
    else:
        run_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)
        name = req.name
        if not name:
            run_index = DB.get_next_run_index(project_id=project_id)
            name = f"Run {run_index}"
        DB.add_run(
            run_id, name, timestamp, req.cwd, req.command,
            req.environment, req.parent_run_id, None,
            project_id=project_id,
        )
        # Request async git versioning
        if project_id and project_root:
            state.request_git_version(run_id, project_id, project_root)

    state.start_run_attempt(
        run_id,
        project_id=project_id,
        project_root=project_root,
        reset_runner_connection=True,
    )
    state.notify_run_list_changed()

    return {"run_id": run_id}


@router.post("/deregister")
def deregister(req: DeregisterRequest, state: ServerState = Depends(get_state)):
    state.touch_activity()
    handle_deregister_message(state, {"run_id": req.run_id})
    # Clean up SSE queue
    state.runner_event_queues.pop(req.run_id, None)
    return {"ok": True}


@router.post("/update-command")
def update_command(req: UpdateCommandRequest, state: ServerState = Depends(get_state)):
    state.touch_activity()
    handle_update_command(state, {"run_id": req.run_id, "command": req.command})
    return {"ok": True}


@router.post("/log")
def log_message(req: LogRequest, state: ServerState = Depends(get_state)):
    state.touch_activity()
    handle_log(state, {"run_id": req.run_id, "metrics": req.metrics})
    return {"ok": True}
