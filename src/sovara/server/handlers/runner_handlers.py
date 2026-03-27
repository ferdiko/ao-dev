"""Handlers for messages received from the agent runner.

These operate on ServerState and have no socket dependencies.
Broadcasting is handled by the route layer after calling these handlers.
"""

from sovara.server.database_manager import DB
from sovara.server.handlers.handler_utils import logger
from sovara.runner.string_matching import clear_matching_data
from sovara.server.graph_models import IncomingNode, SessionGraph


def _find_sessions_with_node(state, node_uuid: str) -> set:
    """Find all sessions containing a specific node UUID."""
    sessions = set()
    for session_id, graph in state.session_graphs.items():
        if graph.node_by_uuid(node_uuid):
            sessions.add(session_id)
    return sessions


def _add_node_to_session(state, sid: str, node: dict, incoming_edges: list) -> None:
    """Add a node to a specific session's graph."""
    graph = state.session_graphs.setdefault(sid, SessionGraph.empty())
    incoming_node = IncomingNode.from_dict(node)
    added_node = graph.add_node(incoming_node, incoming_edges)

    existing_node_uuids = {n.uuid for n in graph.nodes}
    for source_uuid in incoming_edges:
        if source_uuid not in existing_node_uuids:
            logger.debug(
                f"Skipping edge from non-existent node {source_uuid} to {incoming_node.uuid}"
            )
            continue
        edge_id = f"e{source_uuid}-{added_node.uuid}"
        logger.info(f"Added edge {edge_id} in session {sid}")

    state.checkpoint_session_runtime(sid)

    # Update color preview in database
    node_colors = [n.border_color for n in graph.nodes]
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
