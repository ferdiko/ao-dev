import os
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest

from sovara.common.constants import HOST, MAIN_SERVER_LOG, PORT


def _server_request(path: str, method: str = "GET", timeout: float = 1.0) -> bool:
    try:
        request = Request(f"http://{HOST}:{PORT}{path}", method=method)
        with urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except (URLError, OSError):
        return False


def _wait_for_server_ready(timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _server_request("/health"):
            return
        time.sleep(0.25)
    raise RuntimeError(
        f"Timed out waiting for billable test server on {HOST}:{PORT}. "
        f"Check logs at {MAIN_SERVER_LOG}."
    )


@pytest.fixture(scope="session", autouse=True)
def billable_test_server(ensure_test_user_and_project):
    """Run a dedicated server process for the billable test run."""
    log_dir = os.path.dirname(MAIN_SERVER_LOG)
    os.makedirs(log_dir, exist_ok=True)

    if _server_request("/health", timeout=0.25):
        raise RuntimeError(
            f"A server is already responding on the billable test port {PORT}. "
            "Set PYTHON_PORT to an unused port before running billable tests."
        )

    env = os.environ.copy()
    with open(MAIN_SERVER_LOG, "a", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-m", "sovara.cli.so_server", "_serve"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            close_fds=True,
        )

        try:
            _wait_for_server_ready()
            yield
        finally:
            _server_request("/ui/shutdown", method="POST", timeout=1.0)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
