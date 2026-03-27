import uuid

from sovara.server.routes.runner import RegisterRequest, register
from sovara.server.state import ServerState


def test_register_notifies_user_change_when_runner_supplies_user(monkeypatch):
    state = ServerState()
    notifications: list[str] = []

    monkeypatch.setattr(state, "notify_user_changed", lambda: notifications.append("user"))
    monkeypatch.setattr(state, "notify_project_list_changed", lambda: notifications.append("project"))
    monkeypatch.setattr(state, "notify_run_list_changed", lambda: notifications.append("runs"))

    project_id = str(uuid.uuid4())
    response = register(
        RegisterRequest(
            cwd="/tmp",
            command="python script.py",
            environment={},
            name="Run 1",
            project_id=project_id,
            project_name="Project",
            project_description="",
            project_root="/tmp",
            user_id="user-1",
            user_full_name="User One",
            user_email="user@example.com",
        ),
        state,
    )

    run_id = response.get("run_id")
    assert isinstance(run_id, str) and run_id
    assert notifications.count("user") == 1
    assert notifications.count("project") == 1
    assert notifications.count("runs") == 1
