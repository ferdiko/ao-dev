"""Handlers for messages received from the agent runner.

These operate on ServerState and have no socket dependencies.
Broadcasting is handled by the route layer after calling these handlers.
"""

from sovara.server.database import DB
from sovara.server.handlers.handler_utils import logger
from sovara.runner.string_matching import clear_matching_data
from sovara.server.graph_models import IncomingNode, RunGraph


def _find_runs_with_node(state, node_uuid: str) -> set:
    """Find all runs containing a specific node UUID."""
    runs = set()
    for run_id, graph in state.run_graphs.items():
        if graph.get_node_by_uuid(node_uuid):
            runs.add(run_id)
    return runs


def _add_node_to_run(state, run_id: str, node: dict, incoming_edges: list) -> None:
    """Add a node to a specific run's graph."""
    graph = state.run_graphs.setdefault(run_id, RunGraph.empty())
    incoming_node = IncomingNode.from_dict(node)
    added_node = graph.add_node(incoming_node, incoming_edges)

    existing_node_uuids = {n.uuid for n in graph.nodes}
    for source_uuid in incoming_edges:
        if source_uuid not in existing_node_uuids:
            logger.debug(
                f"Skipping edge from non-existent node {source_uuid} to {incoming_node.uuid}"
            )
            continue
    
    state.checkpoint_run_runtime(run_id)

    # Update color preview in database
    node_colors = [n.border_color for n in graph.nodes]
    color_preview = node_colors[-6:]
    DB.update_color_preview(run_id, color_preview)
    DB.update_graph_topology(run_id, graph)

    # Note: color_preview_update and graph_update broadcasts are handled by the route layer


def handle_add_node(state, msg: dict) -> None:
    """Handle add_node message from runner."""
    run_id = msg["run_id"]
    node = msg["node"]
    incoming_edges = msg.get("incoming_edges", [])

    # Lock protects run_graphs: concurrent add_node calls (e.g. ensemble
    # workers) could otherwise write a stale snapshot to the DB.
    with state.lock:
        # Check if any incoming edges reference nodes from other runs.
        cross_session_sources = []
        target_sessions = set()

        for source in incoming_edges:
            source_sessions = _find_runs_with_node(state, source)
            if source_sessions:
                for source_session in source_sessions:
                    target_sessions.add(source_session)
                    cross_session_sources.append(source)

        if target_sessions:
            for target_sid in target_sessions:
                _add_node_to_run(state, target_sid, node, cross_session_sources)
        else:
            _add_node_to_run(state, run_id, node, incoming_edges)


def handle_deregister_message(state, msg: dict) -> None:
    """Handle deregister message from runner."""
    run_id = msg["run_id"]
    run = state.runs.get(run_id)
    if run:
        state.finalize_run_runtime(run_id)
        run.status = "finished"
        clear_matching_data(run_id)
        state.notify_run_list_changed()


def handle_update_command(state, msg: dict) -> None:
    """Update the restart command for a run."""
    run_id = msg.get("run_id")
    command = msg.get("command")
    if run_id and command:
        run = state.runs.get(run_id)
        if run:
            run.command = command
            DB.update_command(run_id, command)


def handle_log(state, msg: dict) -> None:
    """Handle log message from runner."""
    run_id = msg["run_id"]
    metrics = msg["metrics"]
    state.checkpoint_run_runtime(run_id)
    DB.add_metrics(run_id, metrics)
    state.notify_run_list_changed()
