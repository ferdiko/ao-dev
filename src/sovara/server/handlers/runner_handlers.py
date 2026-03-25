"""Handlers for messages received from the agent runner.

These operate on ServerState and have no socket dependencies.
Broadcasting is handled by the route layer after calling these handlers.
"""

from sovara.server.database_manager import DB
from sovara.server.handlers.handler_utils import logger
from sovara.runner.string_matching import clear_matching_data


def _find_sessions_with_node(state, node_id: str) -> set:
    """Find all sessions containing a specific node ID."""
    sessions = set()
    for session_id, graph in state.session_graphs.items():
        if any(node["id"] == node_id for node in graph.get("nodes", [])):
            sessions.add(session_id)
    return sessions


def _add_node_to_session(state, sid: str, node: dict, incoming_edges: list) -> None:
    """Add a node to a specific session's graph."""
    graph = state.session_graphs.setdefault(sid, {"nodes": [], "edges": []})

    # Check for duplicate node
    node_exists = any(n["id"] == node["id"] for n in graph["nodes"])
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
                graph["edges"].append({"id": edge_id, "source": source, "target": target})
                existing_edge_ids.add(edge_id)
                logger.info(f"Added edge {edge_id} in session {sid}")
        else:
            logger.debug(f"Skipping edge from non-existent node {source} to {node['id']}")

    state.checkpoint_session_runtime(sid)

    # Update color preview in database
    node_colors = [n["border_color"] for n in graph["nodes"]]
    color_preview = node_colors[-6:]
    DB.update_color_preview(sid, color_preview)
    DB.update_graph_topology(sid, graph)

    # Note: color_preview_update and graph_update broadcasts are handled by the route layer


def handle_add_node(state, msg: dict) -> None:
    """Handle add_node message from runner."""
    sid = msg["session_id"]
    node = msg["node"]
    incoming_edges = msg.get("incoming_edges", [])

    # Lock protects session_graphs: concurrent add_node calls (e.g. ensemble
    # workers) could otherwise write a stale snapshot to the DB.
    with state.lock:
        # Check if any incoming edges reference nodes from other sessions
        cross_session_sources = []
        target_sessions = set()

        for source in incoming_edges:
            source_sessions = _find_sessions_with_node(state, source)
            if source_sessions:
                for source_session in source_sessions:
                    target_sessions.add(source_session)
                    cross_session_sources.append(source)

        if target_sessions:
            for target_sid in target_sessions:
                _add_node_to_session(state, target_sid, node, cross_session_sources)
        else:
            _add_node_to_session(state, sid, node, incoming_edges)


def handle_deregister_message(state, msg: dict) -> None:
    """Handle deregister message from runner."""
    session_id = msg["session_id"]
    session = state.sessions.get(session_id)
    if session:
        state.finalize_session_runtime(session_id)
        session.status = "finished"
        clear_matching_data(session_id)
        state.notify_experiment_list_changed()


def handle_update_command(state, msg: dict) -> None:
    """Update the restart command for a session."""
    session_id = msg.get("session_id")
    command = msg.get("command")
    if session_id and command:
        session = state.sessions.get(session_id)
        if session:
            session.command = command
            DB.update_command(session_id, command)


def handle_log(state, msg: dict) -> None:
    """Handle log message from runner."""
    session_id = msg["session_id"]
    metrics = msg["metrics"]
    state.checkpoint_session_runtime(session_id)
    DB.add_metrics(session_id, metrics)
    state.notify_experiment_list_changed()
