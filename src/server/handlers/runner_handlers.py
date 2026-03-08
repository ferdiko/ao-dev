"""Handlers for messages received from the agent runner."""

import socket
import uuid
from datetime import datetime

from ao.server.database_manager import DB
from ao.server.handlers.handler_utils import send_json, logger
from ao.runner.string_matching import clear_matching_data


def _find_sessions_with_node(server, node_id: str) -> set:
    """Find all sessions containing a specific node ID. Returns empty set if not found."""
    sessions = set()
    for session_id, graph in server.session_graphs.items():
        if any(node["id"] == node_id for node in graph.get("nodes", [])):
            sessions.add(session_id)
    return sessions


def _add_node_to_session(server, sid: str, node: dict, incoming_edges: list) -> None:
    """Add a node to a specific session's graph."""
    graph = server.session_graphs.setdefault(sid, {"nodes": [], "edges": []})

    # Check for duplicate node
    node_exists = False
    for n in graph["nodes"]:
        if n["id"] == node["id"]:
            node_exists = True
            break
    if not node_exists:
        graph["nodes"].append(node)

    # Build set of existing edge IDs for duplicate checking
    existing_edge_ids = {e["id"] for e in graph["edges"]}
    existing_node_ids = {n["id"] for n in graph["nodes"]}

    # Add incoming edges (only if source nodes exist and edge doesn't already exist)
    for source in incoming_edges:
        if source in existing_node_ids:
            target = node["id"]
            edge_id = f"e{source}-{target}"
            if edge_id not in existing_edge_ids:
                full_edge = {"id": edge_id, "source": source, "target": target}
                graph["edges"].append(full_edge)
                existing_edge_ids.add(edge_id)
                logger.info(f"Added edge {edge_id} in session {sid}")
            else:
                logger.debug(f"Skipping duplicate edge {edge_id}")
        else:
            logger.debug(f"Skipping edge from non-existent node {source} to {node['id']}")

    # Update color preview in database
    node_colors = [n["border_color"] for n in graph["nodes"]]
    color_preview = node_colors[-6:]  # Only display last 6 colors
    DB.update_color_preview(sid, color_preview)

    # Broadcast color preview update to all UIs
    server.broadcast_to_all_uis(
        {"type": "color_preview_update", "session_id": sid, "color_preview": color_preview}
    )
    server.broadcast_graph_update(sid)
    DB.update_graph_topology(sid, graph)


def handle_add_node(server, msg: dict) -> None:
    """Handle add_node message from runner."""
    sid = msg["session_id"]
    node = msg["node"]
    incoming_edges = msg.get("incoming_edges", [])

    # Check if any incoming edges reference nodes from other sessions
    cross_session_sources = []
    target_sessions = set()

    for source in incoming_edges:
        source_sessions = _find_sessions_with_node(server, source)
        if source_sessions:
            for source_session in source_sessions:
                target_sessions.add(source_session)
                cross_session_sources.append(source)

    # If we have cross-session references, add the node to those sessions instead
    if target_sessions:
        for target_sid in target_sessions:
            _add_node_to_session(server, target_sid, node, cross_session_sources)
    else:
        # No cross-session references, add to current session as normal
        _add_node_to_session(server, sid, node, incoming_edges)


def handle_add_subrun(server, msg: dict, conn: socket.socket) -> None:
    """Handle add_subrun message from runner."""
    from ao.server.main_server import Session

    prev_session_id = msg.get("prev_session_id")
    if prev_session_id:
        session_id = prev_session_id
    else:
        session_id = str(uuid.uuid4())
        cwd = msg.get("cwd")
        command = msg.get("command")
        environment = msg.get("environment")
        timestamp = datetime.now()
        name = msg.get("name")
        if not name:
            run_index = DB.get_next_run_index()
            name = f"Run {run_index}"
        parent_session_id = msg.get("parent_session_id")

        DB.add_experiment(
            session_id,
            name,
            timestamp,
            cwd,
            command,
            environment,
            parent_session_id,
            None,  # version_date will be set async
        )
        # Request async git versioning
        server._git_executor.submit(server._do_git_version, session_id)

    # Insert session if not present
    with server.lock:
        if session_id not in server.sessions:
            server.sessions[session_id] = Session(session_id)
        session = server.sessions[session_id]
    with session.lock:
        session.shim_conn = conn
    session.status = "running"
    server.notify_experiment_list_changed()
    server.conn_info[conn] = {"role": "agent-runner", "session_id": session_id}
    response = {"type": "session_id", "session_id": session_id}
    request_id = msg.get("request_id")
    if request_id:
        response["request_id"] = request_id
    send_json(conn, response)


def handle_deregister_message(server, msg: dict) -> None:
    """Handle deregister message from runner."""
    session_id = msg["session_id"]
    session = server.sessions.get(session_id)
    if session:
        session.status = "finished"
        clear_matching_data(session_id)
        server.notify_experiment_list_changed()


def handle_update_command(server, msg: dict) -> None:
    """Update the restart command for a session (sent async after handshake)."""
    session_id = msg.get("session_id")
    command = msg.get("command")
    if session_id and command:
        session = server.sessions.get(session_id)
        if session:
            session.command = command
            DB.update_command(session_id, command)


def handle_log(server, msg: dict) -> None:
    """Handle log message from runner."""
    session_id = msg["session_id"]
    success = msg["success"]
    entry = msg["entry"]
    DB.add_log(session_id, success, entry)
    server.notify_experiment_list_changed()
