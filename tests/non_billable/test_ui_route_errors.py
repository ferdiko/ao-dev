import json
import uuid

from sovara.server.database_manager import DB
from sovara.server.routes.ui import (
    CreateProjectTagRequest,
    EditInputRequest,
    EditOutputRequest,
    RestartRequest,
    create_project_tag,
    edit_input,
    edit_output,
    restart,
)
from sovara.server.state import ServerState


def _response_json(response) -> dict:
    return json.loads(response.body)


def test_restart_missing_session_returns_404():
    missing_session_id = str(uuid.uuid4())
    state = ServerState()

    response = restart(RestartRequest(session_id=missing_session_id), state)

    assert response.status_code == 404
    assert _response_json(response) == {"error": f"Session not found: {missing_session_id}"}


def test_edit_input_missing_node_returns_404():
    session_id = str(uuid.uuid4())
    node_uuid = "missing-node"
    state = ServerState()

    response = edit_input(
        EditInputRequest(session_id=session_id, node_uuid=node_uuid, value="{}"),
        state,
    )

    assert response.status_code == 404
    assert _response_json(response) == {
        "error": f"Input node not found for session_id={session_id}, node_uuid={node_uuid}.",
    }


def test_edit_input_invalid_json_returns_400():
    session_id = str(uuid.uuid4())
    node_uuid = "missing-node"
    state = ServerState()

    response = edit_input(
        EditInputRequest(session_id=session_id, node_uuid=node_uuid, value="{"),
        state,
    )

    assert response.status_code == 400
    assert _response_json(response) == {
        "error": f"Invalid input JSON for session_id={session_id}, node_uuid={node_uuid}: Expecting property name enclosed in double quotes.",
    }


def test_edit_output_missing_node_returns_404():
    session_id = str(uuid.uuid4())
    node_uuid = "missing-node"
    state = ServerState()

    response = edit_output(
        EditOutputRequest(session_id=session_id, node_uuid=node_uuid, value="{}"),
        state,
    )

    assert response.status_code == 404
    assert _response_json(response) == {
        "error": f"Output node not found for session_id={session_id}, node_uuid={node_uuid}.",
    }


def test_edit_output_invalid_json_returns_400():
    session_id = str(uuid.uuid4())
    node_uuid = "missing-node"
    state = ServerState()

    response = edit_output(
        EditOutputRequest(session_id=session_id, node_uuid=node_uuid, value="{"),
        state,
    )

    assert response.status_code == 400
    assert _response_json(response) == {
        "error": f"Invalid output JSON for session_id={session_id}, node_uuid={node_uuid}: Expecting property name enclosed in double quotes.",
    }


def test_create_project_tag_accepts_github_palette_colors():
    project_id = str(uuid.uuid4())
    state = ServerState()
    DB.upsert_project(project_id, "test-project", "")

    try:
        response = create_project_tag(
            project_id,
            CreateProjectTagRequest(name="Ship", color="#1a7f37"),
            state,
        )
    finally:
        DB.delete_project(project_id)

    assert response == {
        "tag": {
            "tag_id": response["tag"]["tag_id"],
            "name": "Ship",
            "color": "#1a7f37",
        },
    }
