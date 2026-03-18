"""UI REST endpoints -- called by VS Code extension and web app."""

import json
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from ao.server.app import get_state
from ao.server.state import ServerState, logger
from ao.server.database_manager import DB
from ao.server.handlers.ui_handlers import (
    handle_edit_input,
    handle_edit_output,
    handle_update_node,
    handle_update_run_name,
    handle_update_result,
    handle_update_notes,
    handle_erase,
)

router = APIRouter(prefix="/ui")


# ============================================================
# Request models
# ============================================================

class EditInputRequest(BaseModel):
    session_id: str
    node_id: str
    value: str


class EditOutputRequest(BaseModel):
    session_id: str
    node_id: str
    value: str


class UpdateNodeRequest(BaseModel):
    session_id: str
    node_id: str
    field: str
    value: str


class UpdateRunNameRequest(BaseModel):
    session_id: str
    run_name: str


class UpdateResultRequest(BaseModel):
    session_id: str
    result: str


class UpdateNotesRequest(BaseModel):
    session_id: str
    notes: str


class RestartRequest(BaseModel):
    session_id: str


class EraseRequest(BaseModel):
    session_id: str


# ============================================================
# Endpoints
# ============================================================

@router.get("/graph/{session_id}")
def get_graph(session_id: str, state: ServerState = Depends(get_state)):
    # Check in-memory graph first
    if session_id in state.session_graphs:
        return {"type": "graph_update", "session_id": session_id, "payload": state.session_graphs[session_id]}

    # Fall back to database
    row = DB.get_graph(session_id)
    if row and row["graph_topology"]:
        graph = json.loads(row["graph_topology"])
        state.session_graphs[session_id] = graph
        return {"type": "graph_update", "session_id": session_id, "payload": graph}

    return {"type": "graph_update", "session_id": session_id, "payload": {"nodes": [], "edges": []}}


@router.get("/experiments")
def get_experiments(state: ServerState = Depends(get_state)):
    state._sweep_dead_sessions()
    session_map = {s.session_id: s for s in state.sessions.values()}
    running_ids = {sid for sid, s in state.sessions.items() if s.status == "running"}

    running_rows = DB.get_experiments_by_ids(running_ids)
    finished_rows = DB.get_experiments_excluding_ids(
        running_ids, limit=state.EXPERIMENT_PAGE_SIZE,
    )
    finished_count = DB.get_experiment_count_excluding_ids(running_ids)
    has_more = finished_count > state.EXPERIMENT_PAGE_SIZE

    experiments = [state._format_experiment_row(row, session_map) for row in running_rows + finished_rows]
    return {"type": "experiment_list", "experiments": experiments, "has_more": has_more}


@router.get("/experiments/more")
def get_more_experiments(offset: int = 0, state: ServerState = Depends(get_state)):
    running_ids = {sid for sid, s in state.sessions.items() if s.status == "running"}
    db_rows = DB.get_experiments_excluding_ids(running_ids, limit=state.EXPERIMENT_PAGE_SIZE, offset=offset)
    finished_count = DB.get_experiment_count_excluding_ids(running_ids)
    has_more = (offset + state.EXPERIMENT_PAGE_SIZE) < finished_count
    session_map = {s.session_id: s for s in state.sessions.values()}
    experiments = [state._format_experiment_row(row, session_map) for row in db_rows]
    return {"type": "more_experiments", "experiments": experiments, "has_more": has_more}


@router.get("/experiment/{session_id}")
def get_experiment_detail(session_id: str, state: ServerState = Depends(get_state)):
    row = DB.get_experiment_detail(session_id)
    notes = row["notes"] if row else ""
    log = row["log"] if row else ""
    return {"type": "experiment_detail", "session_id": session_id, "notes": notes, "log": log}


@router.get("/lessons-applied")
def get_lessons_applied(state: ServerState = Depends(get_state)):
    records = DB.get_all_lessons_applied()
    return {"type": "lessons_applied", "records": records}


@router.post("/edit-input")
def edit_input(req: EditInputRequest, state: ServerState = Depends(get_state)):
    handle_edit_input(state, {"session_id": req.session_id, "node_id": req.node_id, "value": req.value})
    state.schedule_graph_update(req.session_id)
    return {"ok": True}


@router.post("/edit-output")
def edit_output(req: EditOutputRequest, state: ServerState = Depends(get_state)):
    handle_edit_output(state, {"session_id": req.session_id, "node_id": req.node_id, "value": req.value})
    state.schedule_graph_update(req.session_id)
    return {"ok": True}


@router.post("/update-node")
def update_node(req: UpdateNodeRequest, state: ServerState = Depends(get_state)):
    handle_update_node(state, {
        "session_id": req.session_id, "node_id": req.node_id,
        "field": req.field, "value": req.value,
    })
    state.schedule_graph_update(req.session_id)
    return {"ok": True}


@router.post("/update-run-name")
def update_run_name(req: UpdateRunNameRequest, state: ServerState = Depends(get_state)):
    handle_update_run_name(state, {"session_id": req.session_id, "run_name": req.run_name})
    return {"ok": True}


@router.post("/update-result")
def update_result(req: UpdateResultRequest, state: ServerState = Depends(get_state)):
    handle_update_result(state, {"session_id": req.session_id, "result": req.result})
    return {"ok": True}


@router.post("/update-notes")
def update_notes(req: UpdateNotesRequest, state: ServerState = Depends(get_state)):
    handle_update_notes(state, {"session_id": req.session_id, "notes": req.notes})
    return {"ok": True}


@router.post("/restart")
def restart(req: RestartRequest, state: ServerState = Depends(get_state)):
    session_id = req.session_id
    parent_session_id = DB.get_parent_session_id(session_id)
    if not parent_session_id:
        return {"error": "Session not found"}

    # Clear UI state and schedule broadcasts
    state.clear_session_ui_and_schedule_broadcast(session_id)

    session = state.sessions.get(parent_session_id)
    if session and session.status == "running":
        # Send restart to running runner via SSE
        state.schedule_runner_event(parent_session_id, {"type": "restart"})
    elif session and session.status == "finished":
        # Spawn a new process directly
        state.spawn_session_process(parent_session_id, session_id)

    return {"ok": True}


@router.post("/erase")
def erase(req: EraseRequest, state: ServerState = Depends(get_state)):
    handle_erase(state, {"session_id": req.session_id})
    # After erase, trigger restart
    restart(RestartRequest(session_id=req.session_id), state)
    return {"ok": True}


@router.post("/shutdown")
def shutdown(state: ServerState = Depends(get_state)):
    logger.info("Shutdown requested via API")
    state.request_shutdown()
    return {"ok": True}


@router.post("/clear")
def clear(state: ServerState = Depends(get_state)):
    DB.clear_db()
    state.session_graphs.clear()
    state.sessions.clear()
    state.notify_experiment_list_changed()
    state.schedule_broadcast(
        {"type": "graph_update", "session_id": None, "payload": {"nodes": [], "edges": []}}
    )
    return {"ok": True}
