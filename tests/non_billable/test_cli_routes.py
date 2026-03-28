import json
import os
import uuid
from datetime import datetime, timezone

from fastapi.responses import JSONResponse

from sovara.common.constants import TEST_PROJECT_ID, TEST_USER_ID
from sovara.server.database_manager import DB
from sovara.server.graph_models import RunGraph
from sovara.server.handlers.ui_handlers import handle_edit_input
from sovara.server.routes.ui import PrepareEditRerunRequest, prepare_run_edit_rerun, probe_run
from sovara.server.state import ServerState


def _seed_run(run_id: str | None = None, node_uuids: list[str] | None = None) -> tuple[str, list[str]]:
    run_id = run_id or str(uuid.uuid4())
    node_uuids = node_uuids or [str(uuid.uuid4())]
    environment = {"PATH": os.environ.get("PATH", "")}

    DB.add_run(
        run_id=run_id,
        name="Seed Run",
        timestamp=datetime.now(timezone.utc),
        cwd="/tmp",
        command="python -m seeded.workflow",
        environment=environment,
        project_id=TEST_PROJECT_ID,
        user_id=TEST_USER_ID,
    )

    input_to_show = {
        "body": {
            "messages": [{"content": "old prompt"}],
            "max_tokens": 50,
        }
    }
    output_to_show = {"content": "old output"}

    graph_nodes = []
    for index, node_uuid in enumerate(node_uuids, start=1):
        DB.backend.insert_llm_call_with_output_query(
            run_id,
            json.dumps({"raw": input_to_show, "to_show": input_to_show}),
            f"seeded-hash-{index}",
            node_uuid,
            "httpx.Client.send",
            json.dumps({"raw": output_to_show, "to_show": output_to_show}),
            "line one\nline two",
        )
        graph_nodes.append({
            "uuid": node_uuid,
            "step_id": index,
            "input": json.dumps(input_to_show),
            "output": json.dumps(output_to_show),
            "label": f"Seed Node {index}",
            "border_color": "#000000",
            "stack_trace": "line one\nline two",
            "model": None,
            "attachments": [],
        })

    graph = RunGraph.from_dict({
        "nodes": graph_nodes,
        "edges": [],
    })
    DB.update_graph_topology(run_id, graph)
    return run_id, node_uuids


def test_handle_edit_input_updates_persisted_graph_when_run_is_not_loaded():
    run_id, node_uuids = _seed_run()
    node_uuid = node_uuids[0]
    state = ServerState()

    try:
        handle_edit_input(state, {
            "run_id": run_id,
            "node_uuid": node_uuid,
            "value": json.dumps({
                "body": {
                    "messages": [{"content": "new prompt"}],
                    "max_tokens": 50,
                }
            }),
        })

        row = DB.get_graph(run_id)
        graph = RunGraph.from_json_string(row["graph_topology"])
        node = graph.get_node_by_uuid(node_uuid)

        assert node is not None
        assert json.loads(node.input)["body"]["messages"][0]["content"] == "new prompt"
    finally:
        DB.backend.delete_runs_by_ids_query([run_id], user_id=None)


def test_probe_run_prefers_input_overwrite():
    run_id, node_uuids = _seed_run()
    node_uuid = node_uuids[0]
    state = ServerState()

    try:
        DB.set_input_overwrite(
            run_id,
            node_uuid,
            json.dumps({
                "body": {
                    "messages": [{"content": "edited prompt"}],
                    "max_tokens": 50,
                }
            }),
        )

        response = probe_run(
            run_id,
            node=node_uuid,
            nodes="",
            preview=False,
            show_input=False,
            show_output=False,
            key_regex=None,
            state=state,
        )

        assert response["has_input_overwrite"] is True
        assert response["input"]["body.messages.0.content"] == "edited prompt"
    finally:
        DB.backend.delete_runs_by_ids_query([run_id], user_id=None)


def test_prepare_edit_rerun_preserves_run_scope_and_exec_context():
    run_id, node_uuids = _seed_run()
    node_uuid = node_uuids[0]
    state = ServerState()

    try:
        response = prepare_run_edit_rerun(
            run_id,
            PrepareEditRerunRequest(
                node_uuid=node_uuid,
                field="input",
                key="body.messages.0.content",
                value="\"prepared prompt\"",
                run_name="Edited Seed Run",
            ),
            state,
        )

        new_run_id = response["run_id"]
        context = DB.query_one(
            "SELECT project_id, user_id, name, command FROM runs WHERE run_id=?",
            (new_run_id,),
        )
        llm_call = DB.get_llm_call_full(new_run_id, node_uuid)
        graph = RunGraph.from_json_string(DB.get_graph(new_run_id)["graph_topology"])
        node = graph.get_node_by_uuid(node_uuid)

        assert response["command"] == "python -m seeded.workflow"
        assert response["cwd"] == "/tmp"
        assert response["environment"]["PATH"] == os.environ.get("PATH", "")

        assert context["project_id"] == TEST_PROJECT_ID
        assert context["user_id"] == TEST_USER_ID
        assert context["name"] == "Edited Seed Run"
        assert context["command"] == "python -m seeded.workflow"

        assert llm_call["input_overwrite"] is not None
        assert json.loads(llm_call["input_overwrite"])["to_show"]["body"]["messages"][0]["content"] == "prepared prompt"
        assert json.loads(node.input)["body"]["messages"][0]["content"] == "prepared prompt"
    finally:
        cleanup_ids = [run_id]
        if "new_run_id" in locals():
            cleanup_ids.append(new_run_id)
        DB.backend.delete_runs_by_ids_query(cleanup_ids, user_id=None)


def test_probe_run_adds_hint_when_key_regex_matches_nothing():
    run_id, node_uuids = _seed_run()
    node_uuid = node_uuids[0]
    state = ServerState()

    try:
        response = probe_run(
            run_id,
            node=node_uuid,
            nodes="",
            preview=False,
            show_input=False,
            show_output=True,
            key_regex="does_not_exist",
            state=state,
        )

        assert response["output"] == {}
        assert "Re-run probe with --preview on this node" in response["hint"]
    finally:
        DB.backend.delete_runs_by_ids_query([run_id], user_id=None)


def test_probe_run_resolves_unambiguous_run_and_node_prefixes():
    run_id, node_uuids = _seed_run(
        run_id="12345678-1111-4111-8111-111111111111",
        node_uuids=["87654321-2222-4222-8222-222222222222"],
    )
    state = ServerState()

    try:
        response = probe_run(
            run_id[:8],
            node=node_uuids[0][:8],
            nodes="",
            preview=False,
            show_input=False,
            show_output=False,
            key_regex=None,
            state=state,
        )

        assert response["run_id"] == run_id
        assert response["node_uuid"] == node_uuids[0]
    finally:
        DB.backend.delete_runs_by_ids_query([run_id], user_id=None)


def test_probe_run_rejects_ambiguous_run_prefix():
    first_run_id = "deadbeef-1111-4111-8111-111111111111"
    second_run_id = "deadbeef-2222-4222-8222-222222222222"
    cleanup_ids: list[str] = []

    try:
        cleanup_ids.append(_seed_run(run_id=first_run_id)[0])
        cleanup_ids.append(_seed_run(run_id=second_run_id)[0])

        response = probe_run(
            "deadbeef",
            node=None,
            nodes="",
            preview=False,
            show_input=False,
            show_output=False,
            key_regex=None,
            state=ServerState(),
        )

        assert isinstance(response, JSONResponse)
        assert response.status_code == 400
        assert "Ambiguous Run ID prefix 'deadbeef'" in response.body.decode()
    finally:
        DB.backend.delete_runs_by_ids_query(cleanup_ids, user_id=None)


def test_prepare_edit_rerun_rejects_ambiguous_node_prefix():
    run_id, node_uuids = _seed_run(
        run_id="abcdef12-1111-4111-8111-111111111111",
        node_uuids=[
            "feedface-1111-4111-8111-111111111111",
            "feedface-2222-4222-8222-222222222222",
        ],
    )
    state = ServerState()

    try:
        response = prepare_run_edit_rerun(
            run_id[:8],
            PrepareEditRerunRequest(
                node_uuid="feedface",
                field="input",
                key="body.messages.0.content",
                value="\"prepared prompt\"",
                run_name="Edited Seed Run",
            ),
            state,
        )

        assert isinstance(response, JSONResponse)
        assert response.status_code == 400
        assert "Ambiguous Node UUID prefix 'feedface'" in response.body.decode()
    finally:
        DB.backend.delete_runs_by_ids_query([run_id], user_id=None)
