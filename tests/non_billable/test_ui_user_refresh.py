from sovara.server.routes.ui import refresh_user
from sovara.server.state import ServerState


def test_refresh_user_notifies_all_dependent_ui_state(monkeypatch):
    state = ServerState()
    notifications: list[str] = []

    monkeypatch.setattr(state, "notify_user_changed", lambda: notifications.append("user"))
    monkeypatch.setattr(state, "notify_project_list_changed", lambda: notifications.append("projects"))
    monkeypatch.setattr(state, "notify_experiment_list_changed", lambda: notifications.append("experiments"))

    response = refresh_user(state)

    assert response == {"ok": True}
    assert notifications == ["user", "projects", "experiments"]
