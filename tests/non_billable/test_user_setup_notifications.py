import sovara.common.user as user_module
from sovara.server.database import DB


def test_ensure_user_configured_notifies_running_server_after_new_user_setup(monkeypatch):
    created_user = {
        "user_id": "user-1",
        "full_name": "User One",
        "email": "user@example.com",
    }
    upserts: list[tuple[str, str, str]] = []
    notifications: list[str] = []

    monkeypatch.setattr(user_module, "read_user_id", lambda: None)
    monkeypatch.setattr(user_module, "setup_user_interactive", lambda existing=None: created_user)
    monkeypatch.setattr(DB, "upsert_user", lambda user_id, full_name, email: upserts.append((user_id, full_name, email)))
    monkeypatch.setattr(user_module, "_notify_running_server_about_user_change", lambda: notifications.append("user"))

    result = user_module.ensure_user_configured()

    assert result == created_user
    assert upserts == [("user-1", "User One", "user@example.com")]
    assert notifications == ["user"]


def test_ensure_user_configured_does_not_notify_when_user_already_exists(monkeypatch):
    existing_user = {
        "user_id": "user-1",
        "full_name": "User One",
        "email": "user@example.com",
    }
    notifications: list[str] = []

    monkeypatch.setattr(user_module, "read_user_id", lambda: existing_user["user_id"])
    monkeypatch.setattr(DB, "get_user", lambda user_id: existing_user)
    monkeypatch.setattr(user_module, "_notify_running_server_about_user_change", lambda: notifications.append("user"))

    result = user_module.ensure_user_configured()

    assert result == existing_user
    assert notifications == []
