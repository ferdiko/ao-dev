"""Handlers for messages received from the UI (VS Code extension webview)."""

import json
import socket

from ao.common.constants import (
    AO_CONFIG,
    PLAYBOOK_SERVER_URL,
    PLAYBOOK_API_KEY,
)
from ao.server.database_manager import DB
from ao.server.handlers.handler_utils import send_json, logger


def handle_restart_message(server, msg: dict) -> None:
    """Handle restart request from UI."""
    session_id = msg.get("session_id")
    parent_session_id = DB.get_parent_session_id(session_id)
    if not parent_session_id:
        logger.error("Restart message missing session_id. Ignoring.")
        return

    # Clear UI state (updates both memory and database atomically)
    server._clear_session_ui(session_id)

    session = server.sessions.get(parent_session_id)

    if session and session.status == "running":
        # Send graceful restart signal to existing session if still connected
        if session.shim_conn:
            restart_msg = {"type": "restart", "session_id": parent_session_id}
            logger.debug(f"Session running...Sending restart for session_id: {parent_session_id}")
            try:
                send_json(session.shim_conn, restart_msg)
            except Exception as e:
                logger.error(f"Error sending restart: {e}")
            return
        else:
            logger.warning(f"No shim_conn for session_id: {parent_session_id}")
    elif session and session.status == "finished":
        # Rerun for finished session: spawn new process with same session_id
        server._spawn_session_process(parent_session_id, session_id)


def handle_edit_input(server, msg: dict) -> None:
    """Handle input edit from UI."""
    session_id = msg["session_id"]
    node_id = msg["node_id"]
    new_input = msg["value"]

    logger.info(f"[EditIO] edit input msg keys {[*msg.keys()]}")
    logger.info(f"[EditIO] edit input msg: {msg}")

    DB.set_input_overwrite(session_id, node_id, new_input)
    if session_id in server.session_graphs:
        for node in server.session_graphs[session_id]["nodes"]:
            if node["id"] == node_id:
                node["input"] = new_input
                break
        DB.update_graph_topology(session_id, server.session_graphs[session_id])
        server.broadcast_graph_update(session_id)


def handle_edit_output(server, msg: dict) -> None:
    """Handle output edit from UI."""
    session_id = msg["session_id"]
    node_id = msg["node_id"]
    new_output = msg["value"]

    logger.info(f"[EditIO] edit output msg: {msg}")

    DB.set_output_overwrite(session_id, node_id, new_output)
    if session_id in server.session_graphs:
        for node in server.session_graphs[session_id]["nodes"]:
            if node["id"] == node_id:
                node["output"] = new_output
                break
        DB.update_graph_topology(session_id, server.session_graphs[session_id])
        server.broadcast_graph_update(session_id)


def handle_update_node(server, msg: dict) -> None:
    """Handle updateNode message for updating node properties like label."""
    session_id = msg.get("session_id")
    node_id = msg.get("node_id")
    field = msg.get("field")
    value = msg.get("value")

    if not all([session_id, node_id, field]):
        logger.error(f"Missing required fields in updateNode message: {msg}")
        return

    if session_id in server.session_graphs:
        for node in server.session_graphs[session_id]["nodes"]:
            if node["id"] == node_id:
                node[field] = value
                break

        DB.update_graph_topology(session_id, server.session_graphs[session_id])
        server.broadcast_graph_update(session_id)
    else:
        logger.warning(f"Session {session_id} not found in session_graphs")


def handle_update_run_name(server, msg: dict) -> None:
    """Handle experiment name update from UI."""
    session_id = msg.get("session_id")
    run_name = msg.get("run_name")
    if session_id and run_name is not None:
        DB.update_run_name(session_id, run_name)
        server.broadcast_experiment_list_to_uis()
    else:
        logger.error(
            f"handle_update_run_name: Missing required fields: session_id={session_id}, run_name={run_name}"
        )


def handle_update_result(server, msg: dict) -> None:
    """Handle experiment result update from UI."""
    session_id = msg.get("session_id")
    result = msg.get("result")
    if session_id and result is not None:
        DB.update_result(session_id, result)
        server.broadcast_experiment_list_to_uis()
    else:
        logger.error(
            f"handle_update_result: Missing required fields: session_id={session_id}, result={result}"
        )


def handle_update_notes(server, msg: dict) -> None:
    """Handle experiment notes update from UI."""
    session_id = msg.get("session_id")
    notes = msg.get("notes")
    if session_id and notes is not None:
        DB.update_notes(session_id, notes)
        server.broadcast_experiment_list_to_uis()
    else:
        logger.error(
            f"handle_update_notes: Missing required fields: session_id={session_id}, notes={notes}"
        )


def _handle_graph_request(server, conn: socket.socket, session_id: str) -> None:
    """Send graph data for a session to the requesting connection."""
    # Check if we have in-memory graph first (most up-to-date)
    if session_id in server.session_graphs:
        graph = server.session_graphs[session_id]
        send_json(conn, {"type": "graph_update", "session_id": session_id, "payload": graph})
        return

    # Fall back to database if no in-memory graph
    row = DB.get_graph(session_id)
    if row and row["graph_topology"]:
        graph = json.loads(row["graph_topology"])
        server.session_graphs[session_id] = graph
        send_json(conn, {"type": "graph_update", "session_id": session_id, "payload": graph})


def handle_get_graph(server, msg: dict, conn: socket.socket) -> None:
    """Handle graph request from UI."""
    session_id = msg["session_id"]
    _handle_graph_request(server, conn, session_id)


def handle_erase(server, msg: dict) -> None:
    """Handle erase request from UI."""
    session_id = msg.get("session_id")

    DB.erase(session_id)
    DB.update_color_preview(session_id, [])

    server.broadcast_to_all_uis(
        {"type": "color_preview_update", "session_id": session_id, "color_preview": []}
    )

    handle_restart_message(server, {"session_id": session_id})


def handle_get_all_experiments(server, conn: socket.socket) -> None:
    """Handle request to refresh the experiment list (e.g., when VS Code window regains focus)."""
    # First, send current session_id and database_mode to ensure UI state is synced
    send_json(
        conn,
        {
            "type": "session_id",
            "session_id": None,
            "config_path": AO_CONFIG,
            "database_mode": DB.get_current_mode(),
            "playbook_url": PLAYBOOK_SERVER_URL,
            "playbook_api_key": PLAYBOOK_API_KEY,
        },
    )
    # Then send the experiment list
    server.broadcast_experiment_list_to_uis(conn)
