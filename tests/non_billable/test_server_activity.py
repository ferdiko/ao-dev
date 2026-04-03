from fastapi.testclient import TestClient

from sovara.server.app import create_app
from sovara.server.state import ServerState


def test_http_requests_touch_server_activity(monkeypatch):
    touches = []
    original_touch = ServerState.touch_activity

    def fake_touch(self):
        touches.append(True)
        return original_touch(self)

    monkeypatch.setattr("sovara.server.app.inference_server.start", lambda: None)
    monkeypatch.setattr("sovara.server.app.inference_server.stop", lambda: None)
    monkeypatch.setattr(ServerState, "touch_activity", fake_touch)

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert touches


def test_open_ui_websocket_prevents_inactivity_shutdown():
    state = ServerState()
    state._last_activity_time = 0
    state.ui_websockets.add(object())

    assert state.check_inactivity() is False
