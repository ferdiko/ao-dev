"""Handlers for messages received from the UI.

These operate on ServerState and have no socket dependencies.
Broadcasting is handled by the route/events layer after calling these handlers.
"""

from sovara.server.database_manager import DB
from sovara.server.handlers.handler_utils import logger


def handle_edit_input(state, msg: dict) -> None:
    """Handle input edit from UI."""
    session_id = msg["session_id"]
    node_uuid = msg["node_uuid"]
    new_input = msg["value"]

    overwrite = DB.set_input_overwrite(session_id, node_uuid, new_input)
    if overwrite and session_id in state.session_graphs:
        node = state.session_graphs[session_id].get_node_by_uuid(node_uuid)
        if node:
            node.input = new_input  # graph stores to_show for display
        DB.update_graph_topology(session_id, state.session_graphs[session_id])


def handle_edit_output(state, msg: dict) -> None:
    """Handle output edit from UI."""
    session_id = msg["session_id"]
    node_uuid = msg["node_uuid"]
    new_output = msg["value"]

    overwrite = DB.set_output_overwrite(session_id, node_uuid, new_output)
    if overwrite and session_id in state.session_graphs:
        node = state.session_graphs[session_id].get_node_by_uuid(node_uuid)
        if node:
            node.output = new_output  # graph stores to_show for display
        DB.update_graph_topology(session_id, state.session_graphs[session_id])


def handle_update_node(state, msg: dict) -> None:
    """Handle updateNode message for updating node properties like label."""
    session_id = msg.get("session_id")
    node_uuid = msg.get("node_uuid")
    field = msg.get("field")
    value = msg.get("value")

    if not all([session_id, node_uuid, field]):
        logger.error(f"Missing required fields in updateNode message: {msg}")
        return

    if session_id in state.session_graphs:
        node = state.session_graphs[session_id].get_node_by_uuid(node_uuid)
        if node and hasattr(node, field):
            setattr(node, field, value)
        DB.update_graph_topology(session_id, state.session_graphs[session_id])
    else:
        logger.warning(f"Session {session_id} not found in session_graphs")


def handle_update_run_name(state, msg: dict) -> None:
    """Handle experiment name update from UI."""
    session_id = msg.get("session_id")
    run_name = msg.get("run_name")
    if session_id and run_name is not None:
        DB.update_run_name(session_id, run_name)
        state.notify_experiment_list_changed()


def handle_update_thumb_label(state, msg: dict) -> None:
    """Handle experiment thumb label update from UI."""
    session_id = msg.get("session_id")
    thumb_label = msg.get("thumb_label")
    if session_id:
        DB.update_thumb_label(session_id, thumb_label)
        state.notify_experiment_list_changed()


def handle_update_notes(state, msg: dict) -> None:
    """Handle experiment notes update from UI."""
    session_id = msg.get("session_id")
    notes = msg.get("notes")
    if session_id and notes is not None:
        DB.update_notes(session_id, notes)


def handle_erase(state, msg: dict) -> None:
    """Handle erase request from UI (clears LLM calls, not the experiment)."""
    session_id = msg.get("session_id")
    DB.erase(session_id)
    DB.update_color_preview(session_id, [])


def handle_delete_runs(state, msg: dict) -> int:
    """Handle deleting one or more finished runs from UI."""
    session_ids = list(dict.fromkeys(msg.get("session_ids") or []))
    if not session_ids:
        return 0

    deleted = DB.delete_runs(session_ids)

    for session_id in session_ids:
        state.sessions.pop(session_id, None)
        state.session_graphs.pop(session_id, None)
        state.runner_event_queues.pop(session_id, None)
        state.rerun_sessions.discard(session_id)

    state.notify_experiment_list_changed()
    state.notify_project_list_changed()
    return deleted
