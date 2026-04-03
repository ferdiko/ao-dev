"""UI REST endpoints -- called by VS Code extension and web app."""

import asyncio
import os
import time
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, TypeAdapter, ValidationError

from sovara.common.constants import SOVARA_CONFIG, SOVARA_SERVER_URL
from sovara.common.custom_metrics import MetricFilter
from sovara.server.app import get_state
from sovara.server.state import ServerState, logger
from sovara.server.database_manager import DB, BadRequestError, ResourceNotFoundError
from sovara.server.graph_models import RunGraph
from sovara.server.prior_display import attach_ui_prior_counts, build_ui_prior_records
from sovara.common.user import invalidate_user_id_cache, read_user_id, write_user_id
from sovara.common.project import find_project_root, read_project_id, write_project_id, delete_project_configs
from sovara.server.handlers.ui_handlers import (
    handle_delete_runs,
    handle_edit_input,
    handle_edit_output,
    handle_update_node,
    handle_update_run_name,
    handle_update_thumb_label,
    handle_update_notes,
    handle_erase,
)
from sovara.server.handlers.cli_handlers import (
    build_probe_response,
    prepare_edit_rerun,
)

router = APIRouter(prefix="/ui")

TAG_COLORS = {
    "#0969da",
    "#1a7f37",
    "#cf222e",
    "#bf8700",
    "#8250df",
    "#e85aad",
    "#0598d5",
    "#d1570a",
    "#5e60ce",
    "#1b8a72",
}

def _request_error_response(exc: Exception) -> JSONResponse:
    status_code = 404 if isinstance(exc, ResourceNotFoundError) else 400
    return JSONResponse(status_code=status_code, content={"error": str(exc)})


def _extract_http_error_detail(resp) -> str:
    try:
        data = resp.json()
    except ValueError:
        text = resp.text.strip()
        return text or "Chat error"

    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
        error = data.get("error")
        if isinstance(error, str) and error.strip():
            return error

    return "Chat error"


def _notify_user_state_changed(state: ServerState) -> None:
    """Broadcast all UI invalidations caused by a local-user identity change."""
    state.notify_user_changed()
    state.notify_project_list_changed()
    state.notify_run_list_changed()


def _attach_prior_metadata_to_graph(run_id: str, graph: RunGraph) -> RunGraph:
    prior_rows = DB.get_prior_retrievals_for_run(run_id)
    if not prior_rows:
        return graph
    return attach_ui_prior_counts(graph, prior_rows)


def _get_ui_prior_records(run_id: str, graph: RunGraph | None = None) -> dict[str, dict]:
    prior_rows = DB.get_prior_retrievals_for_run(run_id)
    if not prior_rows:
        return {}
    if graph is None:
        row = DB.get_run_metadata(run_id)
        graph = RunGraph.from_json_string(row["graph_topology"] if row else None)
    return build_ui_prior_records(graph, prior_rows)


# ============================================================
# Request models
# ============================================================

class EditInputRequest(BaseModel):
    run_id: str
    node_uuid: str
    value: str


class EditOutputRequest(BaseModel):
    run_id: str
    node_uuid: str
    value: str


class UpdateNodeRequest(BaseModel):
    run_id: str
    node_uuid: str
    field: str
    value: str


class UpdateRunNameRequest(BaseModel):
    run_id: str
    name: str


class UpdateThumbLabelRequest(BaseModel):
    run_id: str
    thumb_label: bool | None


class UpdateNotesRequest(BaseModel):
    run_id: str
    notes: str


class RestartRequest(BaseModel):
    run_id: str


class EraseRequest(BaseModel):
    run_id: str


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    location: str


class SetupUserRequest(BaseModel):
    full_name: str
    email: str


class UpdateUserRequest(BaseModel):
    full_name: str
    email: str


class DeleteUserRequest(BaseModel):
    confirmation_name: str


class UpdateProjectLocationRequest(BaseModel):
    project_id: str
    old_location: str
    new_location: str


class DeleteProjectLocationRequest(BaseModel):
    project_id: str
    location: str


class UpdateProjectRequest(BaseModel):
    project_id: str
    name: str
    description: str = ""


class DeleteProjectRequest(BaseModel):
    project_id: str
    confirmation_name: str


class DeleteRunsRequest(BaseModel):
    run_ids: list[str]


class CreateProjectTagRequest(BaseModel):
    name: str
    color: str


class DeleteProjectTagRequest(BaseModel):
    tag_id: str


class UpdateRunTagsRequest(BaseModel):
    run_id: str
    tag_ids: list[str]


class PrepareEditRerunRequest(BaseModel):
    node_uuid: str
    field: str
    key: str
    value: str
    run_name: str | None = None


# ============================================================
# Endpoints
# ============================================================

@router.get("/config")
def get_ui_config():
    """Return static UI bootstrap configuration."""
    return {
        "config_path": SOVARA_CONFIG,
        "priors_url": SOVARA_SERVER_URL,
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
    return {"user": {"user_id": row["user_id"], "full_name": row["full_name"], "email": row["email"]}}


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
    _notify_user_state_changed(state)
    return {"user": {"user_id": user_id, "full_name": req.full_name.strip(), "email": req.email.strip()}}


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
    _notify_user_state_changed(state)
    return {"user": {"user_id": user_id, "full_name": req.full_name.strip(), "email": req.email.strip()}}


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
    # Remove .sovara/ folders at every project location before deleting DB records
    delete_project_configs(DB.get_user_project_locations(user_id))
    DB.delete_user(user_id)
    # Remove the .user_id file
    from sovara.common.constants import USER_ID_PATH
    if os.path.isfile(USER_ID_PATH):
        os.remove(USER_ID_PATH)
    invalidate_user_id_cache()
    _notify_user_state_changed(state)
    return {"ok": True}


@router.post("/refresh-user")
def refresh_user(state: ServerState = Depends(get_state)):
    """Broadcast that the local user identity changed outside the server process."""
    invalidate_user_id_cache()
    _notify_user_state_changed(state)
    return {"ok": True}


@router.post("/pick-directory")
def pick_directory():
    """Open native OS folder picker and return the selected path."""
    import subprocess
    import sys

    path = None
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["osascript", "-e", 'POSIX path of (choose folder with prompt "Select Project Location")'],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                path = result.stdout.strip().rstrip("/")
        elif sys.platform == "win32":
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0 and result.stdout.strip():
                path = result.stdout.strip()
        else:  # Linux
            for cmd in [["zenity", "--file-selection", "--directory", "--title=Select Project Location"],
                        ["kdialog", "--getexistingdirectory", "."]]:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if result.returncode == 0 and result.stdout.strip():
                        path = result.stdout.strip()
                        break
                except FileNotFoundError:
                    continue
    except subprocess.TimeoutExpired:
        pass

    return {"path": path}


@router.post("/create-project")
def create_project(req: CreateProjectRequest):
    """Create a new project with validation."""
    user_id = read_user_id()
    if not user_id:
        return JSONResponse(status_code=403, content={
            "error": "No user configured. Run so-record once to set up your user profile."
        })

    location = os.path.abspath(req.location)

    if not os.path.isdir(location):
        return JSONResponse(status_code=400, content={"error": f"Directory does not exist: {location}"})

    # Check if name is already taken
    for p in DB.get_all_projects():
        if p["name"] == req.name:
            return JSONResponse(status_code=409, content={"error": f"A project named '{req.name}' already exists."})

    # Check if location already belongs to a project
    project_root = find_project_root(location)
    if project_root:
        existing_id = read_project_id(project_root)
        existing = DB.get_project(existing_id)
        name = existing["name"] if existing else existing_id
        return JSONResponse(status_code=409, content={
            "error": f"This directory is already part of project '{name}' (root: {project_root})."
        })

    # Create the project
    project_id = str(uuid.uuid4())
    write_project_id(location, project_id)
    DB.upsert_project(project_id, req.name, req.description)
    DB.upsert_project_location(user_id, project_id, location)

    return {"project_id": project_id, "name": req.name}


@router.post("/update-project-location")
def update_project_location(req: UpdateProjectLocationRequest):
    """Update a project location (e.g. after moving the project folder)."""
    user_id = read_user_id()
    if not user_id:
        return JSONResponse(status_code=403, content={"error": "No user configured."})

    new_location = os.path.abspath(req.new_location)
    if not os.path.isdir(new_location):
        return JSONResponse(status_code=400, content={"error": f"Directory does not exist: {new_location}"})

    # Write .sovara/.project_id at new location
    write_project_id(new_location, req.project_id)

    # Replace old location with new
    DB.delete_project_location(user_id, req.project_id, req.old_location)
    DB.upsert_project_location(user_id, req.project_id, new_location)

    return {"ok": True}


@router.post("/update-project")
def update_project(req: UpdateProjectRequest, state: ServerState = Depends(get_state)):
    """Update project name and description."""
    project = DB.get_project(req.project_id)
    if not project:
        return JSONResponse(status_code=404, content={"error": "Project not found."})
    if not req.name.strip():
        return JSONResponse(status_code=400, content={"error": "Project name is required."})
    for p in DB.get_all_projects():
        if p["name"] == req.name.strip() and p["project_id"] != req.project_id:
            return JSONResponse(status_code=409, content={"error": f"A project named '{req.name.strip()}' already exists."})
    DB.upsert_project(req.project_id, req.name.strip(), req.description.strip())
    state.notify_project_list_changed()
    return {"project": {"project_id": req.project_id, "name": req.name.strip(), "description": req.description.strip()}}


@router.post("/delete-project-location")
def delete_project_location(req: DeleteProjectLocationRequest):
    """Remove a single project location."""
    user_id = read_user_id()
    if not user_id:
        return JSONResponse(status_code=403, content={"error": "No user configured."})
    DB.delete_project_location(user_id, req.project_id, req.location)
    delete_project_configs([req.location])
    return {"ok": True}


@router.post("/delete-project")
def delete_project(req: DeleteProjectRequest, state: ServerState = Depends(get_state)):
    """Delete an entire project and all associated data."""
    project = DB.get_project(req.project_id)
    if not project:
        return JSONResponse(status_code=404, content={"error": "Project not found."})
    if req.confirmation_name != project["name"]:
        return JSONResponse(status_code=400, content={"error": "Name does not match."})
    # Remove .sovara/ directories at all project locations before cascading DB delete
    locations = DB.get_all_project_locations(req.project_id)
    delete_project_configs([row["project_location"] for row in locations])
    DB.delete_project(req.project_id)
    state.notify_run_list_changed()
    state.notify_project_list_changed()
    return {"ok": True}


@router.post("/delete-runs")
def delete_runs(req: DeleteRunsRequest, state: ServerState = Depends(get_state)):
    """Delete one or more runs visible to the current user."""
    run_ids = [run_id for run_id in req.run_ids if run_id]
    if not run_ids:
        return JSONResponse(status_code=400, content={"error": "At least one run_id is required."})

    deleted = handle_delete_runs(state, {"run_ids": run_ids})
    return {"ok": True, "deleted": deleted}


def _validate_location(path: str, expected_project_id: str) -> bool:
    """Check if a location is valid: directory exists and .sovara/.project_id matches."""
    if not os.path.isdir(path):
        return False
    project_root = find_project_root(path)
    if not project_root:
        return False
    try:
        return read_project_id(project_root) == expected_project_id
    except Exception:
        return False


@router.get("/projects")
def get_projects(state: ServerState = Depends(get_state)):
    """List all projects with run counts and location sync status."""
    projects = DB.get_all_projects()
    result = []
    for p in projects:
        pid = p["project_id"]
        run_count = DB.get_run_count(project_id=pid)
        location_rows = DB.get_all_project_locations(pid)
        locations = []
        location_warning = False
        for row in location_rows:
            path = row["project_location"]
            valid = _validate_location(path, pid)
            locations.append({"path": path, "valid": valid})
            if not valid:
                location_warning = True
        result.append({
            "project_id": pid,
            "name": p["name"],
            "description": p["description"] or "",
            "created_at": p["created_at"],
            "last_run_at": p["last_run_at"],
            "num_runs": run_count,
            "num_users": DB.get_project_user_count(pid),
            "locations": locations,
            "location_warning": location_warning,
        })
    return {"projects": result}


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    """Get a single project by ID."""
    project = DB.get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content={"error": "Project not found."})
    return {
        "project_id": project["project_id"],
        "name": project["name"],
        "description": project["description"] or "",
    }


@router.get("/projects/{project_id}/tags")
def get_project_tags(project_id: str):
    project = DB.get_project(project_id)
    if not project:
        return JSONResponse(status_code=404, content={"error": "Project not found."})
    return {"tags": DB.get_project_tags(project_id)}


@router.post("/projects/{project_id}/tags")
def create_project_tag(project_id: str, req: CreateProjectTagRequest, state: ServerState = Depends(get_state)):
    if req.color not in TAG_COLORS:
        return JSONResponse(status_code=400, content={"error": "Invalid tag color."})
    try:
        tag = DB.create_project_tag(project_id, req.name.strip(), req.color)
    except ValueError as exc:
        message = str(exc)
        if "already exists" in message:
            status_code = 409
        elif "Project not found" in message:
            status_code = 404
        else:
            status_code = 400
        return JSONResponse(status_code=status_code, content={"error": message})
    state.notify_run_list_changed()
    return {"tag": tag}


@router.post("/projects/{project_id}/tags/delete")
def delete_project_tag(project_id: str, req: DeleteProjectTagRequest, state: ServerState = Depends(get_state)):
    try:
        DB.delete_project_tag(project_id, req.tag_id)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        return JSONResponse(status_code=status_code, content={"error": message})
    state.notify_run_list_changed()
    return {"ok": True}


@router.get("/projects/{project_id}/runs")
def get_project_runs(
    project_id: str,
    limit: int = 50,
    offset: int = 0,
    sort: str = "timestamp",
    dir: str = "desc",
    name: str = "",
    run_id: str = "",
    label: list[str] = Query(default=[]),
    tag_id: list[str] = Query(default=[]),
    version: list[str] = Query(default=[]),
    metric_filters: str = "",
    time_from: str = "",
    time_to: str = "",
    latency_min: float | None = None,
    latency_max: float | None = None,
    state: ServerState = Depends(get_state),
):
    """Get paginated filtered finished runs plus the current running set for a project."""
    run_map, running_ids = state.get_run_snapshot()

    filters = {}
    if name:
        filters["name"] = name
    if run_id:
        filters["run_id"] = run_id
    if label:
        filters["thumb_label"] = label
    if tag_id:
        filters["tag_ids"] = tag_id
    if version:
        filters["version_date"] = version
    if time_from:
        filters["timestamp_from"] = time_from
    if time_to:
        filters["timestamp_to"] = time_to
    if latency_min is not None and latency_max is not None and latency_min > latency_max:
        return JSONResponse(status_code=400, content={"error": "latency_min cannot be greater than latency_max"})
    if latency_min is not None:
        filters["latency_min"] = latency_min
    if latency_max is not None:
        filters["latency_max"] = latency_max
    if metric_filters:
        try:
            filters["custom_metrics"] = TypeAdapter(dict[str, MetricFilter]).validate_json(metric_filters)
        except ValidationError as exc:
            return JSONResponse(status_code=400, content={"error": exc.errors()})

    running_rows = DB.get_runs_by_ids(running_ids, project_id=project_id)
    running = [state._format_run_row(row, run_map) for row in running_rows]

    finished_rows, finished_total, custom_metric_columns = DB.get_run_table_view(
        project_id=project_id, exclude_ids=running_ids, filters=filters,
        sort_key=sort, sort_dir=dir, limit=limit, offset=offset,
    )
    finished = [state._format_run_row(row, run_map) for row in finished_rows]

    distinct_versions = DB.get_distinct_versions(project_id)

    return {
        "type": "run_list",
        "running": running,
        "finished": finished,
        "finished_total": finished_total,
        "distinct_versions": distinct_versions,
        "custom_metric_columns": custom_metric_columns,
    }


@router.get("/graph/{run_id}")
def get_graph(run_id: str, state: ServerState = Depends(get_state)):
    # Check in-memory graph first
    if run_id in state.run_graphs:
        graph = _attach_prior_metadata_to_graph(run_id, state.run_graphs[run_id])
        return {
            "type": "graph_update",
            "run_id": run_id,
            "payload": graph.to_dict(),
            "active_runtime_seconds": state.get_persisted_active_runtime_seconds(run_id),
        }

    # Fall back to database
    row = DB.get_graph(run_id)
    if row and row["graph_topology"]:
        graph = RunGraph.from_json_string(row["graph_topology"])
        graph = _attach_prior_metadata_to_graph(run_id, graph)
        state.run_graphs[run_id] = graph
        return {
            "type": "graph_update",
            "run_id": run_id,
            "payload": graph.to_dict(),
            "active_runtime_seconds": state.get_persisted_active_runtime_seconds(run_id),
        }

    return {
        "type": "graph_update",
        "run_id": run_id,
        "payload": {"nodes": [], "edges": []},
        "active_runtime_seconds": state.get_persisted_active_runtime_seconds(run_id),
    }


@router.get("/run/{run_id}/probe")
def probe_run(
    run_id: str,
    node: str | None = None,
    nodes: str = "",
    preview: bool = False,
    show_input: bool = Query(default=False, alias="input"),
    show_output: bool = Query(default=False, alias="output"),
    key_regex: str | None = None,
    state: ServerState = Depends(get_state),
):
    try:
        node_uuids = [item.strip() for item in nodes.split(",") if item.strip()] or None
        return build_probe_response(
            run_id,
            state=state,
            node_uuid=node,
            node_uuids=node_uuids,
            preview=preview,
            show_input=show_input,
            show_output=show_output,
            key_regex=key_regex,
        )
    except (BadRequestError, ResourceNotFoundError) as exc:
        return _request_error_response(exc)


@router.get("/runs")
def get_runs(state: ServerState = Depends(get_state)):
    run_map, running_ids = state.get_run_snapshot()

    running_rows = DB.get_runs_by_ids(running_ids)
    finished_rows = DB.get_runs_excluding_ids(
        running_ids, limit=state.RUN_PAGE_SIZE,
    )
    finished_count = DB.get_run_count_excluding_ids(running_ids)
    has_more = finished_count > state.RUN_PAGE_SIZE

    runs = [state._format_run_row(row, run_map) for row in running_rows + finished_rows]
    return {"type": "run_list", "runs": runs, "has_more": has_more}


@router.get("/runs/more")
def get_more_runs(offset: int = 0, state: ServerState = Depends(get_state)):
    run_map, running_ids = state.get_run_snapshot()
    db_rows = DB.get_runs_excluding_ids(running_ids, limit=state.RUN_PAGE_SIZE, offset=offset)
    finished_count = DB.get_run_count_excluding_ids(running_ids)
    has_more = (offset + state.RUN_PAGE_SIZE) < finished_count
    runs = [state._format_run_row(row, run_map) for row in db_rows]
    return {"type": "more_runs", "runs": runs, "has_more": has_more}


@router.get("/run/{run_id}")
def get_run_detail(run_id: str, state: ServerState = Depends(get_state)):
    row = DB.get_run_detail(run_id)
    run_map, _ = state.get_run_snapshot()
    run = run_map.get(run_id)
    status = run.status if run else "finished"
    if not row:
        return {"type": "run_detail", "run_id": run_id,
                "name": "", "timestamp": "", "runtime_seconds": None, "active_runtime_seconds": None,
                "custom_metrics": {}, "thumb_label": None, "tags": [], "notes": "", "log": "", "version_date": None, "status": status}
    return {
        "type": "run_detail",
        "run_id": run_id,
        "name": row["name"] or "",
        "timestamp": row["timestamp"] or "",
        "runtime_seconds": DB._normalize_runtime_seconds(row["runtime_seconds"]),
        "active_runtime_seconds": DB._normalize_runtime_seconds(row["active_runtime_seconds"]),
        "custom_metrics": DB._parse_custom_metrics(row["custom_metrics"]),
        "thumb_label": DB._normalize_thumb_label(row["thumb_label"]),
        "tags": row.get("tags", []),
        "notes": row["notes"] or "",
        "log": row["log"] or "",
        "version_date": row["version_date"],
        "status": status,
    }


@router.get("/run/{run_id}/prior-retrieval/{node_uuid}")
def get_node_prior_retrieval(run_id: str, node_uuid: str):
    row = DB.get_llm_call_full(run_id, node_uuid)
    if not row:
        return _request_error_response(
            ResourceNotFoundError(f"Node not found for run_id={run_id}, node_uuid={node_uuid}.")
        )

    graph_row = DB.get_run_metadata(run_id)
    graph = RunGraph.from_json_string(graph_row["graph_topology"] if graph_row else None)
    ui_records = _get_ui_prior_records(run_id, graph=graph)

    return {
        "type": "prior_retrieval",
        "run_id": run_id,
        "node_uuid": node_uuid,
        "record": ui_records.get(node_uuid) or DB.get_prior_retrieval(run_id, node_uuid),
    }


@router.get("/run/{run_id}/prior-retrievals")
def get_run_prior_retrievals(run_id: str):
    row = DB.get_run_metadata(run_id)
    graph = RunGraph.from_json_string(row["graph_topology"] if row else None)
    return {
        "type": "prior_retrievals",
        "run_id": run_id,
        "records": list(_get_ui_prior_records(run_id, graph=graph).values())
        or DB.get_prior_retrievals_for_run(run_id),
    }


@router.get("/priors-applied/{run_id}")
def get_priors_applied(run_id: str, state: ServerState = Depends(get_state)):
    records = DB.get_priors_applied_for_run(run_id)
    return {"type": "priors_applied", "run_id": run_id, "records": records}


@router.get("/runs-for-prior/{prior_id}")
def get_runs_for_prior(prior_id: str, state: ServerState = Depends(get_state)):
    records = DB.get_runs_for_prior(prior_id)
    return {"type": "runs_for_prior", "prior_id": prior_id, "records": records}


@router.post("/edit-input")
def edit_input(req: EditInputRequest, state: ServerState = Depends(get_state)):
    try:
        handle_edit_input(
            state,
            {"run_id": req.run_id, "node_uuid": req.node_uuid, "value": req.value},
        )
    except (BadRequestError, ResourceNotFoundError) as exc:
        return _request_error_response(exc)
    state.schedule_graph_update(req.run_id)
    return {"ok": True}


@router.post("/edit-output")
def edit_output(req: EditOutputRequest, state: ServerState = Depends(get_state)):
    try:
        handle_edit_output(
            state,
            {"run_id": req.run_id, "node_uuid": req.node_uuid, "value": req.value},
        )
    except (BadRequestError, ResourceNotFoundError) as exc:
        return _request_error_response(exc)
    state.schedule_graph_update(req.run_id)
    return {"ok": True}


@router.post("/update-node")
def update_node(req: UpdateNodeRequest, state: ServerState = Depends(get_state)):
    handle_update_node(state, {
        "run_id": req.run_id, "node_uuid": req.node_uuid,
        "field": req.field, "value": req.value,
    })
    state.schedule_graph_update(req.run_id)
    return {"ok": True}


@router.post("/update-run-name")
def update_run_name(req: UpdateRunNameRequest, state: ServerState = Depends(get_state)):
    handle_update_run_name(state, {"run_id": req.run_id, "name": req.name})
    return {"ok": True}


@router.post("/update-thumb-label")
def update_thumb_label(req: UpdateThumbLabelRequest, state: ServerState = Depends(get_state)):
    handle_update_thumb_label(state, {"run_id": req.run_id, "thumb_label": req.thumb_label})
    return {"ok": True}


@router.post("/update-run-tags")
def update_run_tags(req: UpdateRunTagsRequest, state: ServerState = Depends(get_state)):
    try:
        tags = DB.replace_run_tags(req.run_id, req.tag_ids)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        return JSONResponse(status_code=status_code, content={"error": message})
    state.notify_run_list_changed()
    return {"ok": True, "tags": tags}


@router.post("/update-notes")
def update_notes(req: UpdateNotesRequest, state: ServerState = Depends(get_state)):
    handle_update_notes(state, {"run_id": req.run_id, "notes": req.notes})
    return {"ok": True}


@router.post("/restart")
def restart(req: RestartRequest, state: ServerState = Depends(get_state)):
    run_id = req.run_id
    try:
        parent_run_id = DB.get_parent_run_id(run_id)
    except ResourceNotFoundError as exc:
        return _request_error_response(exc)

    run_map, _ = state.get_run_snapshot()
    parent_run = run_map.get(parent_run_id)
    # Capture status before start_run_attempt mutates the shared Run object
    # (run_id == parent_run_id for normal runs, so they share the same object)
    parent_was_running = parent_run.status == "running" if parent_run else False
    parent_had_live_runner = parent_was_running and parent_run_id in state.runner_event_queues

    state.start_run_attempt(run_id)

    # Clear UI state and schedule broadcasts
    state.clear_run_ui_and_schedule_broadcast(run_id)

    if parent_had_live_runner:
        # Send restart to running runner via SSE
        state.schedule_runner_event(parent_run_id, {"type": "restart"})
    elif parent_run:
        # Distinct parent runs can remain stale "running" in memory after their
        # runner transport disappears. Reconcile that state before spawning directly.
        if parent_was_running and parent_run_id != run_id:
            state.checkpoint_interrupted_run_runtime(parent_run_id)
            parent_run.status = "finished"
            state.notify_run_list_changed()
        # Spawn a new process directly
        state.spawn_run_process(parent_run_id, run_id)

    return {"ok": True}


@router.post("/run/{run_id}/prepare-edit-rerun")
def prepare_run_edit_rerun(
    run_id: str,
    req: PrepareEditRerunRequest,
    state: ServerState = Depends(get_state),
):
    try:
        return prepare_edit_rerun(
            state,
            run_id,
            node_uuid=req.node_uuid,
            field=req.field,
            key=req.key,
            value=req.value,
            run_name=req.run_name,
        )
    except (BadRequestError, ResourceNotFoundError) as exc:
        return _request_error_response(exc)


@router.post("/erase")
def erase(req: EraseRequest, state: ServerState = Depends(get_state)):
    handle_erase(state, {"run_id": req.run_id})
    # After erase, trigger restart
    restart(RestartRequest(run_id=req.run_id), state)
    return {"ok": True}


@router.post("/shutdown")
def shutdown(state: ServerState = Depends(get_state)):
    logger.info("Shutdown requested via API")
    state.request_shutdown()
    return {"ok": True}


@router.post("/clear")
def clear(state: ServerState = Depends(get_state)):
    DB.clear_db()
    state.run_graphs.clear()
    state.runs.clear()
    state.notify_run_list_changed()
    state.schedule_broadcast(
        {"type": "graph_update", "run_id": None, "payload": {"nodes": [], "edges": []}}
    )
    return {"ok": True}


# ============================================================
# Trace Chat proxy
# ============================================================

class ChatMessageRequest(BaseModel):
    message: str
    history: list = []


class PersistedTraceChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class PersistedTraceChatHistoryRequest(BaseModel):
    history: list[PersistedTraceChatMessage]


@router.get("/trace-chat/{run_id}")
def get_trace_chat_history(run_id: str):
    try:
        history = DB.get_trace_chat_history(run_id)
    except (BadRequestError, ResourceNotFoundError) as exc:
        return _request_error_response(exc)
    return {"history": history}


@router.post("/trace-chat/{run_id}")
def update_trace_chat_history(run_id: str, req: PersistedTraceChatHistoryRequest):
    try:
        DB.update_trace_chat_history(
            run_id,
            [message.model_dump() for message in req.history],
        )
        history = DB.get_trace_chat_history(run_id)
    except (BadRequestError, ResourceNotFoundError) as exc:
        return _request_error_response(exc)
    return {"history": history}


@router.post("/trace-chat/{run_id}/clear")
def clear_trace_chat_history(run_id: str):
    try:
        DB.clear_trace_chat_history(run_id)
    except (BadRequestError, ResourceNotFoundError) as exc:
        return _request_error_response(exc)
    return {"history": []}


@router.post("/prefetch/{run_id}", status_code=202)
async def prefetch_trace(
    run_id: str,
    state: ServerState = Depends(get_state),
):
    run_map, _running_ids = state.get_run_snapshot()
    run = run_map.get(run_id)
    if run and run.status == "running":
        # Don't prefetch while still running (summary will be invalid shortly)
        return {"status": "skipped", "reason": "run_still_active"}

    import httpx
    from sovara.common.constants import HOST, INFERENCE_PORT
    async with httpx.AsyncClient() as client:
        await client.post(
            f"http://{HOST}:{INFERENCE_PORT}/prefetch/{run_id}",
            timeout=5.0,
        )
    return {"status": "prefetching"}


@router.post("/chat/{run_id}")
async def chat(run_id: str, req: ChatMessageRequest):
    import httpx
    from fastapi import HTTPException
    from sovara.common.constants import HOST, INFERENCE_PORT

    trace_chat_id = uuid.uuid4().hex[:8]
    started_at = time.monotonic()
    logger.info(
        "Trace chat proxy start: id=%s run_id=%s history_messages=%d message_chars=%d",
        trace_chat_id,
        run_id,
        len(req.history),
        len(req.message),
    )

    persisted_history = list(req.history) + [{"role": "user", "content": req.message}]
    try:
        await asyncio.to_thread(DB.update_trace_chat_history, run_id, persisted_history)
        logger.info(
            "Trace chat proxy pre-persist complete: id=%s run_id=%s elapsed=%.3fs",
            trace_chat_id,
            run_id,
            time.monotonic() - started_at,
        )
    except (BadRequestError, ResourceNotFoundError) as exc:
        # Keep the chat proxy path authoritative for request errors. Missing or
        # stale DB state should not mask upstream inference failures.
        logger.warning(
            "Trace chat proxy pre-persist failed: id=%s run_id=%s error=%s elapsed=%.3fs",
            trace_chat_id,
            run_id,
            exc,
            time.monotonic() - started_at,
        )
    except Exception:
        logger.exception(
            "Trace chat proxy pre-persist crashed: id=%s run_id=%s elapsed=%.3fs",
            trace_chat_id,
            run_id,
            time.monotonic() - started_at,
        )

    timeout_seconds = 120.0
    try:
        async with httpx.AsyncClient() as client:
            logger.info(
                "Trace chat proxy upstream request start: id=%s run_id=%s timeout=%.1fs elapsed=%.3fs",
                trace_chat_id,
                run_id,
                timeout_seconds,
                time.monotonic() - started_at,
            )
            resp = await client.post(
                f"http://{HOST}:{INFERENCE_PORT}/chat/{run_id}",
                json=req.model_dump(),
                headers={"x-sovara-trace-chat-id": trace_chat_id},
                timeout=timeout_seconds,
            )
            logger.info(
                "Trace chat proxy upstream response received: id=%s run_id=%s status=%d elapsed=%.3fs",
                trace_chat_id,
                run_id,
                resp.status_code,
                time.monotonic() - started_at,
            )
    except httpx.TimeoutException:
        logger.error(
            "Trace chat proxy timed out: id=%s run_id=%s timeout=%.1fs elapsed=%.3fs",
            trace_chat_id,
            run_id,
            timeout_seconds,
            time.monotonic() - started_at,
        )
        raise HTTPException(504, f"Trace chat timed out after {int(timeout_seconds)} seconds")
    except httpx.HTTPError as e:
        logger.error(
            "Trace chat proxy failed: id=%s run_id=%s error=%s elapsed=%.3fs",
            trace_chat_id,
            run_id,
            e,
            time.monotonic() - started_at,
        )
        raise HTTPException(502, "Could not reach inference server")
    if resp.status_code != 200:
        logger.warning(
            "Trace chat proxy upstream returned non-200: id=%s run_id=%s status=%d detail=%s elapsed=%.3fs",
            trace_chat_id,
            run_id,
            resp.status_code,
            _extract_http_error_detail(resp),
            time.monotonic() - started_at,
        )
        raise HTTPException(resp.status_code, _extract_http_error_detail(resp))
    try:
        data = resp.json()
        logger.info(
            "Trace chat proxy upstream JSON parsed: id=%s run_id=%s keys=%s elapsed=%.3fs",
            trace_chat_id,
            run_id,
            sorted(data.keys()) if isinstance(data, dict) else type(data).__name__,
            time.monotonic() - started_at,
        )
    except ValueError:
        logger.error(
            "Trace chat proxy upstream returned invalid JSON: id=%s run_id=%s elapsed=%.3fs",
            trace_chat_id,
            run_id,
            time.monotonic() - started_at,
        )
        raise HTTPException(502, "Invalid response from inference server")

    answer = data.get("answer")
    if isinstance(answer, str):
        try:
            await asyncio.to_thread(
                DB.update_trace_chat_history,
                run_id,
                persisted_history + [{"role": "assistant", "content": answer}],
            )
            logger.info(
                "Trace chat proxy post-persist complete: id=%s run_id=%s answer_chars=%d elapsed=%.3fs",
                trace_chat_id,
                run_id,
                len(answer),
                time.monotonic() - started_at,
            )
        except (BadRequestError, ResourceNotFoundError) as exc:
            logger.warning(
                "Trace chat proxy post-persist failed: id=%s run_id=%s error=%s elapsed=%.3fs",
                trace_chat_id,
                run_id,
                exc,
                time.monotonic() - started_at,
            )
        except Exception:
            logger.exception(
                "Trace chat proxy post-persist crashed: id=%s run_id=%s elapsed=%.3fs",
                trace_chat_id,
                run_id,
                time.monotonic() - started_at,
            )
    logger.info(
        "Trace chat proxy complete: id=%s run_id=%s answered=%s elapsed=%.3fs",
        trace_chat_id,
        run_id,
        isinstance(answer, str),
        time.monotonic() - started_at,
    )
    return data
