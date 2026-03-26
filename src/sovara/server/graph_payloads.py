"""Helpers for UI-facing graph payloads."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy


def enrich_graph_for_ui(graph: dict | None) -> dict:
    """Attach deterministic UI step identifiers without mutating stored graph data."""
    if not graph:
        return {"nodes": [], "edges": []}

    nodes = list(graph.get("nodes", []))
    edges = list(graph.get("edges", []))
    if not nodes:
        return {"nodes": [], "edges": deepcopy(edges)}

    order = _topological_node_order(nodes, edges)
    step_by_node_id = {
        node_id: {"step_index": index, "step_id": f"step {index}"}
        for index, node_id in enumerate(order, start=1)
    }

    enriched_nodes = []
    for node in nodes:
        enriched = deepcopy(node)
        step_meta = step_by_node_id.get(node.get("id"))
        if step_meta:
            enriched.update(step_meta)
        enriched_nodes.append(enriched)

    return {"nodes": enriched_nodes, "edges": deepcopy(edges)}


def _topological_node_order(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Return a stable node order for UI numbering."""
    node_ids = [node.get("id") for node in nodes if node.get("id")]
    node_index = {node_id: index for index, node_id in enumerate(node_ids)}

    incoming_count: dict[str, int] = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source not in node_index or target not in node_index:
            continue
        outgoing[source].append(target)
        incoming_count[target] += 1

    ready = [node_id for node_id in node_ids if incoming_count[node_id] == 0]
    ready.sort(key=node_index.__getitem__)

    ordered: list[str] = []
    while ready:
        node_id = ready.pop(0)
        ordered.append(node_id)
        for target in sorted(outgoing.get(node_id, []), key=node_index.__getitem__):
            incoming_count[target] -= 1
            if incoming_count[target] == 0:
                ready.append(target)
        ready.sort(key=node_index.__getitem__)

    if len(ordered) == len(node_ids):
        return ordered

    remaining = [node_id for node_id in node_ids if node_id not in set(ordered)]
    remaining.sort(key=node_index.__getitem__)
    return ordered + remaining
