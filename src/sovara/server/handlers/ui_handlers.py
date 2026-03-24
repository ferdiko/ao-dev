"""Handlers for messages received from the UI.

These operate on ServerState and have no socket dependencies.
Broadcasting is handled by the route/events layer after calling these handlers.
"""

from sovara.server.database_manager import DB
from sovara.server.handlers.handler_utils import logger


def handle_edit_input(state, msg: dict) -> None:
    """Handle input edit from UI."""
    session_id = msg["session_id"]
    node_id = msg["node_id"]
    new_input = msg["value"]

    overwrite = DB.set_input_overwrite(session_id, node_id, new_input)
    if overwrite and session_id in state.session_graphs:
        for node in state.session_graphs[session_id]["nodes"]:
            if node["id"] == node_id:
                node["input"] = new_input  # graph stores to_show for display
                break
        DB.update_graph_topology(session_id, state.session_graphs[session_id])


def handle_edit_output(state, msg: dict) -> None:
    """Handle output edit from UI."""
    session_id = msg["session_id"]
    node_id = msg["node_id"]
    new_output = msg["value"]

    overwrite = DB.set_output_overwrite(session_id, node_id, new_output)
    if overwrite and session_id in state.session_graphs:
        for node in state.session_graphs[session_id]["nodes"]:
            if node["id"] == node_id:
                node["output"] = new_output  # graph stores to_show for display
                break
        DB.update_graph_topology(session_id, state.session_graphs[session_id])


def handle_update_node(state, msg: dict) -> None:
    """Handle updateNode message for updating node properties like label."""
    session_id = msg.get("session_id")
    node_id = msg.get("node_id")
    field = msg.get("field")
    value = msg.get("value")

    if not all([session_id, node_id, field]):
        logger.error(f"Missing required fields in updateNode message: {msg}")
        return

    if session_id in state.session_graphs:
        for node in state.session_graphs[session_id]["nodes"]:
            if node["id"] == node_id:
                node[field] = value
                break
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


def handle_update_result(state, msg: dict) -> None:
    """Handle experiment result update from UI."""
    session_id = msg.get("session_id")
    result = msg.get("result")
    if session_id and result is not None:
        DB.update_result(session_id, result)
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
