from types import SimpleNamespace

import httpx
import pytest

from sovara.server.priors_client import PriorsBackendClient, PriorsBackendError


def test_priors_client_retries_once_after_start(monkeypatch):
    calls = []
    ensured = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, *args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 1:
                raise httpx.ConnectError("connection refused")
            return SimpleNamespace(status_code=200, json=lambda: {"status": "ok"})

    monkeypatch.setattr("sovara.server.priors_client.httpx.Client", lambda *args, **kwargs: FakeClient())
    monkeypatch.setattr(
        PriorsBackendClient,
        "_ensure_backend_running",
        lambda self: ensured.append(True) or True,
    )

    client = PriorsBackendClient(user_id="u1", project_id="p1")
    result = client.list_priors()

    assert result == {"status": "ok"}
    assert len(calls) == 2
    assert ensured == [True]


def test_priors_client_raises_502_when_restart_does_not_help(monkeypatch):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, *args, **kwargs):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("sovara.server.priors_client.httpx.Client", lambda *args, **kwargs: FakeClient())
    monkeypatch.setattr(PriorsBackendClient, "_ensure_backend_running", lambda self: False)

    client = PriorsBackendClient(user_id="u1", project_id="p1")

    with pytest.raises(PriorsBackendError) as exc_info:
        client.list_priors()

    assert exc_info.value.status_code == 502
    assert "Unable to reach priors backend" in str(exc_info.value)
