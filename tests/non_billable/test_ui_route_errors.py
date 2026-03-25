import json
import uuid

from sovara.server.routes.ui import (
    EditInputRequest,
    EditOutputRequest,
    RestartRequest,
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
    node_id = "missing-node"
    state = ServerState()

    response = edit_input(
        EditInputRequest(session_id=session_id, node_id=node_id, value="{}"),
        state,
    )

    assert response.status_code == 404
    assert _response_json(response) == {
        "error": f"Input node not found for session_id={session_id}, node_id={node_id}.",
    }


def test_edit_input_invalid_json_returns_400():
    session_id = str(uuid.uuid4())
    node_id = "missing-node"
    state = ServerState()

    response = edit_input(
        EditInputRequest(session_id=session_id, node_id=node_id, value="{"),
        state,
    )

    assert response.status_code == 400
    assert _response_json(response) == {
        "error": f"Invalid input JSON for session_id={session_id}, node_id={node_id}: Expecting property name enclosed in double quotes.",
    }


def test_edit_output_missing_node_returns_404():
    session_id = str(uuid.uuid4())
    node_id = "missing-node"
    state = ServerState()

    response = edit_output(
        EditOutputRequest(session_id=session_id, node_id=node_id, value="{}"),
        state,
    )

    assert response.status_code == 404
    assert _response_json(response) == {
        "error": f"Output node not found for session_id={session_id}, node_id={node_id}.",
    }


def test_edit_output_invalid_json_returns_400():
    session_id = str(uuid.uuid4())
    node_id = "missing-node"
    state = ServerState()

    response = edit_output(
        EditOutputRequest(session_id=session_id, node_id=node_id, value="{"),
        state,
    )

    assert response.status_code == 400
    assert _response_json(response) == {
        "error": f"Invalid output JSON for session_id={session_id}, node_id={node_id}: Expecting property name enclosed in double quotes.",
    }
