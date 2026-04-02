"""Run and graph-related UI routes."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, TypeAdapter, ValidationError

from sovara.common.custom_metrics import MetricFilter
from sovara.server.app import get_state
from sovara.server.database_manager import DB, BadRequestError, ResourceNotFoundError
from sovara.server.graph_models import RunGraph
from sovara.server.handlers.cli_handlers import build_probe_response, prepare_edit_rerun
from sovara.server.handlers.ui_handlers import (
    handle_delete_runs,
    handle_edit_input,
    handle_edit_output,
    handle_erase,
    handle_update_node,
    handle_update_notes,
    handle_update_run_name,
    handle_update_thumb_label,
)
from sovara.server.state import ServerState, logger

from .ui_common import request_error_response

router = APIRouter()


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


class DeleteRunsRequest(BaseModel):
    run_ids: list[str]


class UpdateRunTagsRequest(BaseModel):
    run_id: str
    tag_ids: list[str]


class PrepareEditRerunRequest(BaseModel):
    node_uuid: str
    field: str
    key: str
    value: str
    run_name: str | None = None


@router.post("/delete-runs")
def delete_runs(req: DeleteRunsRequest, state: ServerState = Depends(get_state)):
    """Delete one or more runs visible to the current user."""
    run_ids = [run_id for run_id in req.run_ids if run_id]
    if not run_ids:
        return JSONResponse(status_code=400, content={"error": "At least one run_id is required."})

    deleted = handle_delete_runs(state, {"run_ids": run_ids})
    return {"ok": True, "deleted": deleted}


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
        project_id=project_id,
        exclude_ids=running_ids,
        filters=filters,
        sort_key=sort,
        sort_dir=dir,
        limit=limit,
        offset=offset,
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
    if run_id in state.run_graphs:
        return {
            "type": "graph_update",
            "run_id": run_id,
            "payload": state.run_graphs[run_id].to_dict(),
            "active_runtime_seconds": state.get_persisted_active_runtime_seconds(run_id),
        }

    row = DB.get_graph(run_id)
    if row and row["graph_topology"]:
        graph = RunGraph.from_json_string(row["graph_topology"])
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
        return request_error_response(exc)


@router.get("/runs")
def get_runs(state: ServerState = Depends(get_state)):
    run_map, running_ids = state.get_run_snapshot()

    running_rows = DB.get_runs_by_ids(running_ids)
    finished_rows = DB.get_runs_excluding_ids(running_ids, limit=state.RUN_PAGE_SIZE)
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
        return {
            "type": "run_detail",
            "run_id": run_id,
            "name": "",
            "timestamp": "",
            "runtime_seconds": None,
            "active_runtime_seconds": None,
            "custom_metrics": {},
            "thumb_label": None,
            "tags": [],
            "notes": "",
            "log": "",
            "version_date": None,
            "status": status,
        }
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
        return request_error_response(exc)
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
        return request_error_response(exc)
    state.schedule_graph_update(req.run_id)
    return {"ok": True}


@router.post("/update-node")
def update_node(req: UpdateNodeRequest, state: ServerState = Depends(get_state)):
    handle_update_node(state, {
        "run_id": req.run_id,
        "node_uuid": req.node_uuid,
        "field": req.field,
        "value": req.value,
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


def _restart_run(state: ServerState, run_id: str):
    try:
        parent_run_id = DB.get_parent_run_id(run_id)
    except ResourceNotFoundError as exc:
        return request_error_response(exc)

    run_map, _ = state.get_run_snapshot()
    parent_run = run_map.get(parent_run_id)
    parent_was_running = parent_run.status == "running" if parent_run else False
    parent_had_live_runner = parent_was_running and parent_run_id in state.runner_event_queues

    state.start_run_attempt(run_id)
    state.clear_run_ui_and_schedule_broadcast(run_id)

    if parent_had_live_runner:
        state.schedule_runner_event(parent_run_id, {"type": "restart"})
    elif parent_run:
        if parent_was_running and parent_run_id != run_id:
            state.checkpoint_interrupted_run_runtime(parent_run_id)
            parent_run.status = "finished"
            state.notify_run_list_changed()
        state.spawn_run_process(parent_run_id, run_id)

    return None


@router.post("/restart")
def restart(req: RestartRequest, state: ServerState = Depends(get_state)):
    response = _restart_run(state, req.run_id)
    if response is not None:
        return response
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
        return request_error_response(exc)


@router.post("/erase")
def erase(req: EraseRequest, state: ServerState = Depends(get_state)):
    handle_erase(state, {"run_id": req.run_id})
    _restart_run(state, req.run_id)
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
