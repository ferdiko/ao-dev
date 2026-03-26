from sovara.server.graph_payloads import enrich_graph_for_ui


def test_enrich_graph_assigns_topological_step_ids():
    graph = {
        "nodes": [
            {"id": "c", "label": "C"},
            {"id": "a", "label": "A"},
            {"id": "b", "label": "B"},
        ],
        "edges": [
            {"id": "ea-b", "source": "a", "target": "b"},
            {"id": "eb-c", "source": "b", "target": "c"},
        ],
    }

    enriched = enrich_graph_for_ui(graph)

    assert [node["id"] for node in enriched["nodes"]] == ["c", "a", "b"]
    assert {node["id"]: node["step_id"] for node in enriched["nodes"]} == {
        "a": "step 1",
        "b": "step 2",
        "c": "step 3",
    }


def test_enrich_graph_uses_original_order_as_parallel_tiebreaker():
    graph = {
        "nodes": [
            {"id": "root", "label": "Root"},
            {"id": "right", "label": "Right"},
            {"id": "left", "label": "Left"},
        ],
        "edges": [
            {"id": "eroot-right", "source": "root", "target": "right"},
            {"id": "eroot-left", "source": "root", "target": "left"},
        ],
    }

    enriched = enrich_graph_for_ui(graph)

    assert {node["id"]: node["step_id"] for node in enriched["nodes"]} == {
        "root": "step 1",
        "right": "step 2",
        "left": "step 3",
    }


def test_enrich_graph_is_non_mutating():
    graph = {"nodes": [{"id": "a"}], "edges": []}

    enriched = enrich_graph_for_ui(graph)

    assert enriched["nodes"][0]["step_id"] == "step 1"
    assert "step_id" not in graph["nodes"][0]
