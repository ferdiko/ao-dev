from pathlib import Path

from fastapi.testclient import TestClient

from sovara.server.priors_backend.app import create_app
from sovara.server.priors_backend import server as priors_server


def test_priors_backend_app_exposes_health_and_info():
    client = TestClient(create_app())

    health = client.get("/health")
    info = client.get("/api/v1/info")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "priors_backend"}
    assert info.status_code == 200
    assert info.json()["status"] == "bootstrapped"


def test_resolve_bind_host_port_uses_priors_server_url(monkeypatch):
    monkeypatch.setattr(priors_server, "PRIORS_SERVER_URL", "https://priors.example.com")
    assert priors_server._resolve_bind_host_port() == ("priors.example.com", 443)

    monkeypatch.setattr(priors_server, "PRIORS_SERVER_URL", "http://127.0.0.1:6123")
    assert priors_server._resolve_bind_host_port() == ("127.0.0.1", 6123)


def test_start_spawns_priors_backend_process_and_stop_terminates_it(monkeypatch, tmp_path):
    popen_calls = []

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.terminated = False
            self.killed = False
            self.wait_calls = []

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    fake_process = FakeProcess()

    def fake_popen(args, stdout=None, stderr=None, close_fds=None):
        popen_calls.append(
            {
                "args": args,
                "stdout": stdout,
                "stderr": stderr,
                "close_fds": close_fds,
            }
        )
        return fake_process

    monkeypatch.setattr(priors_server, "PRIORS_SERVER_URL", "http://127.0.0.1:6123")
    monkeypatch.setattr(priors_server, "PRIORS_SERVER_LOG", str(tmp_path / "priors_server.log"))
    monkeypatch.setattr(priors_server.subprocess, "Popen", fake_popen)
    priors_server._process = None

    try:
        priors_server.start()

        assert len(popen_calls) == 1
        assert popen_calls[0]["args"][-4:] == ["--host", "127.0.0.1", "--port", "6123"]
        assert Path(priors_server.PRIORS_SERVER_LOG).exists()

        priors_server.start()
        assert len(popen_calls) == 1

        priors_server.stop()
        assert fake_process.terminated is True
        assert fake_process.killed is False
        assert priors_server._process is None
    finally:
        priors_server._process = None
