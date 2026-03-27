import json
import os
import uuid
from datetime import datetime, timezone

from sovara.common.constants import TEST_PROJECT_ID, TEST_USER_ID
from sovara.server.database_manager import DB
from sovara.server.graph_models import RunGraph
from sovara.server.handlers.ui_handlers import handle_edit_input
from sovara.server.routes.ui import PrepareEditRerunRequest, prepare_run_edit_rerun, probe_run
from sovara.server.state import ServerState


def _seed_run() -> tuple[str, str]:
    run_id = str(uuid.uuid4())
    node_uuid = str(uuid.uuid4())
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

    DB.backend.insert_llm_call_with_output_query(
        run_id,
        json.dumps({"raw": input_to_show, "to_show": input_to_show}),
        "seeded-hash",
        node_uuid,
        "httpx.Client.send",
        json.dumps({"raw": output_to_show, "to_show": output_to_show}),
        "line one\nline two",
    )

    graph = RunGraph.from_dict({
        "nodes": [{
            "uuid": node_uuid,
            "step_id": 1,
            "input": json.dumps(input_to_show),
            "output": json.dumps(output_to_show),
            "label": "Seed Node",
            "border_color": "#000000",
            "stack_trace": "line one\nline two",
            "model": None,
            "attachments": [],
        }],
        "edges": [],
    })
    DB.update_graph_topology(run_id, graph)
    return run_id, node_uuid


def test_handle_edit_input_updates_persisted_graph_when_run_is_not_loaded():
    run_id, node_uuid = _seed_run()
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
    run_id, node_uuid = _seed_run()
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
    run_id, node_uuid = _seed_run()
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
