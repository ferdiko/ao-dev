from sovara.server.graph_models import IncomingNode, SessionGraph


def _incoming(uuid: str, label: str) -> IncomingNode:
    return IncomingNode(
        uuid=uuid,
        input="{}",
        output="{}",
        label=label,
        border_color="#000000",
    )


def test_session_graph_assigns_monotonic_step_ids():
    graph = SessionGraph.empty()

    graph.add_node(_incoming("a", "A"), [])
    graph.add_node(_incoming("b", "B"), ["a"])
    graph.add_node(_incoming("c", "C"), ["b"])

    assert [node.uuid for node in graph.nodes] == ["a", "b", "c"]
    assert [node.step_id for node in graph.nodes] == [1, 2, 3]


def test_session_graph_preserves_arrival_order_for_parallel_nodes():
    graph = SessionGraph.empty()

    graph.add_node(_incoming("root", "Root"), [])
    graph.add_node(_incoming("right", "Right"), ["root"])
    graph.add_node(_incoming("left", "Left"), ["root"])

    assert [(node.uuid, node.step_id) for node in graph.nodes] == [
        ("root", 1),
        ("right", 2),
        ("left", 3),
    ]


def test_session_graph_serialization_round_trip():
    graph = SessionGraph.empty()
    graph.add_node(_incoming("a", "A"), [])
    graph.add_node(_incoming("b", "B"), ["a"])

    restored = SessionGraph.from_dict(graph.to_dict())

    assert restored.to_dict() == graph.to_dict()
    assert restored.edges[0].source_uuid == "a"
    assert restored.edges[0].target_uuid == "b"
