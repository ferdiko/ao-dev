"""Handlers for messages received from the UI.

These operate on ServerState and have no socket dependencies.
Broadcasting is handled by the route/events layer after calling these handlers.
"""

from sovara.server.database import DB
from sovara.server.graph_models import RunGraph
from sovara.server.handlers.handler_utils import logger


def _load_graph_for_edit(state, run_id: str) -> RunGraph | None:
    """Return a mutable graph for a run, loading it from DB if needed."""
    graph = state.run_graphs.get(run_id)
    if graph is not None:
        return graph

    row = DB.get_graph(run_id)
    if not row or not row["graph_topology"]:
        return None

    graph = RunGraph.from_json_string(row["graph_topology"])
    state.run_graphs[run_id] = graph
    return graph


def handle_edit_input(state, msg: dict) -> None:
    """Handle input edit from UI."""
    run_id = msg["run_id"]
    node_uuid = msg["node_uuid"]
    new_input = msg["value"]

    overwrite = DB.set_input_overwrite(run_id, node_uuid, new_input)
    graph = _load_graph_for_edit(state, run_id)
    if overwrite and graph:
        node = graph.get_node_by_uuid(node_uuid)
        if node:
            node.input = new_input  # graph stores to_show for display
        DB.update_graph_topology(run_id, graph)


def handle_edit_output(state, msg: dict) -> None:
    """Handle output edit from UI."""
    run_id = msg["run_id"]
    node_uuid = msg["node_uuid"]
    new_output = msg["value"]

    overwrite = DB.set_output_overwrite(run_id, node_uuid, new_output)
    graph = _load_graph_for_edit(state, run_id)
    if overwrite and graph:
        node = graph.get_node_by_uuid(node_uuid)
        if node:
            node.output = new_output  # graph stores to_show for display
        DB.update_graph_topology(run_id, graph)


def handle_update_node(state, msg: dict) -> None:
    """Handle updateNode message for updating node properties like label."""
    run_id = msg.get("run_id")
    node_uuid = msg.get("node_uuid")
    field = msg.get("field")
    value = msg.get("value")

    if not all([run_id, node_uuid, field]):
        logger.error(f"Missing required fields in updateNode message: {msg}")
        return

    graph = _load_graph_for_edit(state, run_id)
    if graph:
        node = graph.get_node_by_uuid(node_uuid)
        if node and hasattr(node, field):
            setattr(node, field, value)
        DB.update_graph_topology(run_id, graph)
    else:
        logger.warning(f"Run {run_id} not found in run_graphs")


def handle_update_run_name(state, msg: dict) -> None:
    """Handle run name update from UI."""
    run_id = msg.get("run_id")
    name = msg.get("name")
    if run_id and name is not None:
        DB.update_run_name(run_id, name)
        state.notify_run_list_changed()


def handle_update_thumb_label(state, msg: dict) -> None:
    """Handle run thumb label update from UI."""
    run_id = msg.get("run_id")
    thumb_label = msg.get("thumb_label")
    if run_id:
        DB.update_thumb_label(run_id, thumb_label)
        state.notify_run_list_changed()


def handle_update_notes(state, msg: dict) -> None:
    """Handle run notes update from UI."""
    run_id = msg.get("run_id")
    notes = msg.get("notes")
    if run_id and notes is not None:
        DB.update_notes(run_id, notes)


def handle_erase(state, msg: dict) -> None:
    """Handle erase request from UI (clears LLM calls, not the run)."""
    run_id = msg.get("run_id")
    DB.erase(run_id)
    DB.update_color_preview(run_id, [])


def handle_delete_runs(state, msg: dict) -> int:
    """Handle deleting one or more finished runs from UI."""
    run_ids = list(dict.fromkeys(msg.get("run_ids") or []))
    if not run_ids:
        return 0

    deleted = DB.delete_runs(run_ids)

    for run_id in run_ids:
        state.runs.pop(run_id, None)
        state.run_graphs.pop(run_id, None)
        state.runner_event_queues.pop(run_id, None)
        state.rerun_run_ids.discard(run_id)

    state.notify_run_list_changed()
    state.notify_project_list_changed()
    return deleted
