"""Typed graph models for persisted and UI-facing execution graphs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class IncomingNode:
    """Validated node payload received from the runner before graph insertion."""

    uuid: str
    input: str
    output: str
    label: str
    border_color: str
    stack_trace: str | None = None
    node_kind: str | None = None
    prior_count: int | None = None
    raw_node_name: str | None = None
    attachments: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IncomingNode":
        return cls(
            uuid=str(data["uuid"]),
            input=str(data["input"]),
            output=str(data["output"]),
            label=str(data["label"]),
            border_color=str(data["border_color"]),
            stack_trace=None if data.get("stack_trace") is None else str(data["stack_trace"]),
            node_kind=None if data.get("node_kind") is None else str(data["node_kind"]),
            prior_count=None if data.get("prior_count") is None else int(data["prior_count"]),
            raw_node_name=None if data.get("raw_node_name") is None else str(data["raw_node_name"]),
            attachments=list(data.get("attachments") or []),
        )


@dataclass(slots=True)
class GraphNode:
    """Canonical graph node stored in memory and in graph_topology."""

    uuid: str
    step_id: int
    input: str
    output: str
    label: str
    border_color: str
    stack_trace: str | None = None
    node_kind: str | None = None
    prior_count: int | None = None
    raw_node_name: str | None = None
    attachments: list[str] | None = None

    @classmethod
    def from_incoming(cls, node: IncomingNode, step_id: int) -> "GraphNode":
        return cls(
            uuid=node.uuid,
            step_id=step_id,
            input=node.input,
            output=node.output,
            label=node.label,
            border_color=node.border_color,
            stack_trace=node.stack_trace,
            node_kind=node.node_kind,
            prior_count=node.prior_count,
            raw_node_name=node.raw_node_name,
            attachments=node.attachments,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphNode":
        return cls(
            uuid=str(data["uuid"]),
            step_id=int(data["step_id"]),
            input=str(data["input"]),
            output=str(data["output"]),
            label=str(data["label"]),
            border_color=str(data["border_color"]),
            stack_trace=None if data.get("stack_trace") is None else str(data["stack_trace"]),
            node_kind=None if data.get("node_kind") is None else str(data["node_kind"]),
            prior_count=None if data.get("prior_count") is None else int(data["prior_count"]),
            raw_node_name=None if data.get("raw_node_name") is None else str(data["raw_node_name"]),
            attachments=list(data.get("attachments") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "step_id": self.step_id,
            "input": self.input,
            "output": self.output,
            "label": self.label,
            "border_color": self.border_color,
            "stack_trace": self.stack_trace,
            "node_kind": self.node_kind,
            "prior_count": self.prior_count,
            "raw_node_name": self.raw_node_name,
            "attachments": self.attachments or [],
        }


@dataclass(slots=True)
class GraphEdge:
    """Directed dataflow edge between two graph nodes."""

    id: str
    source_uuid: str
    target_uuid: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphEdge":
        return cls(
            id=str(data["id"]),
            source_uuid=str(data["source_uuid"]),
            target_uuid=str(data["target_uuid"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_uuid": self.source_uuid,
            "target_uuid": self.target_uuid,
        }


@dataclass(slots=True)
class RunGraph:
    """Typed run graph persisted to graph_topology and served to UIs."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    @classmethod
    def empty(cls) -> "RunGraph":
        return cls(nodes=[], edges=[])

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RunGraph":
        if not data:
            return cls.empty()
        return cls(
            nodes=[GraphNode.from_dict(node) for node in data.get("nodes", [])],
            edges=[GraphEdge.from_dict(edge) for edge in data.get("edges", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    @classmethod
    def from_json_string(cls, data: str | None) -> "RunGraph":
        if not data:
            return cls.empty()
        return cls.from_dict(json.loads(data))

    def to_json_string(self) -> str:
        return json.dumps(self.to_dict())

    def get_node_by_uuid(self, node_uuid: str) -> GraphNode | None:
        for node in self.nodes:
            if node.uuid == node_uuid:
                return node
        return None

    def add_node(self, incoming: IncomingNode, incoming_source_uuids: list[str]) -> GraphNode:
        existing = self.get_node_by_uuid(incoming.uuid)
        if existing is None:
            existing = GraphNode.from_incoming(incoming, step_id=len(self.nodes) + 1)
            self.nodes.append(existing)

        existing_edge_ids = {edge.id for edge in self.edges}
        existing_node_uuids = {node.uuid for node in self.nodes}
        for source_uuid in incoming_source_uuids:
            if source_uuid not in existing_node_uuids:
                continue
            edge_id = f"e{source_uuid}-{existing.uuid}"
            if edge_id in existing_edge_ids:
                continue
            self.edges.append(
                GraphEdge(id=edge_id, source_uuid=source_uuid, target_uuid=existing.uuid)
            )
            existing_edge_ids.add(edge_id)

        return existing

    def assert_valid_step_ids(self) -> None:
        expected = list(range(1, len(self.nodes) + 1))
        actual = [node.step_id for node in self.nodes]
        if actual != expected:
            raise ValueError(f"Invalid step ids: expected {expected}, got {actual}")
