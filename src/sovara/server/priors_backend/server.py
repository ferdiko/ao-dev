"""Priors backend child service process manager and entrypoint."""

import argparse
import os
import subprocess
import sys
import time
from typing import Optional
from urllib.parse import urlparse
from urllib.request import urlopen
from urllib.error import URLError

from sovara.common.constants import MAIN_SERVER_LOG, PRIORS_SERVER_LOG, PRIORS_SERVER_URL, PROCESS_TERMINATE_TIMEOUT
from sovara.common.logger import create_file_logger
from sovara.server.priors_backend.app import create_app

app = create_app()
manager_logger = create_file_logger(MAIN_SERVER_LOG)

_process: Optional[subprocess.Popen] = None


def _resolve_bind_host_port() -> tuple[str, int]:
    parsed = urlparse(PRIORS_SERVER_URL)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port is not None:
        return host, parsed.port
    if parsed.scheme == "https":
        return host, 443
    return host, 80


def _is_priors_backend_running(timeout: float = 1.0) -> bool:
    try:
        with urlopen(f"{PRIORS_SERVER_URL}/health", timeout=timeout) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def wait_until_healthy(timeout: float = 2.5, poll_interval: float = 0.1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_priors_backend_running(timeout=min(1.0, poll_interval)):
            return True
        if _process is not None and _process.poll() is not None:
            return False
        time.sleep(poll_interval)
    return _is_priors_backend_running(timeout=min(1.0, poll_interval))


def start() -> None:
    """Spawn the priors backend as a child process."""
    global _process
    if _process is not None and _process.poll() is None:
        manager_logger.info("Priors backend already tracked in-process (pid=%s)", _process.pid)
        return
    if _is_priors_backend_running():
        manager_logger.info("Reusing already-healthy priors backend at %s", PRIORS_SERVER_URL)
        return

    host, port = _resolve_bind_host_port()
    os.makedirs(os.path.dirname(PRIORS_SERVER_LOG), exist_ok=True)
    log_f = open(PRIORS_SERVER_LOG, "a")
    manager_logger.info("Starting priors backend on %s (host=%s port=%s)", PRIORS_SERVER_URL, host, port)
    _process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "sovara.server.priors_backend.server",
            "--host",
            host,
            "--port",
            str(port),
        ],
        stdout=log_f,
        stderr=subprocess.STDOUT,
        close_fds=True,
    )
    if wait_until_healthy():
        manager_logger.info("Priors backend is healthy (pid=%s)", _process.pid)
        return

    exit_code = _process.poll()
    if exit_code is None:
        manager_logger.error(
            "Priors backend did not become healthy within startup timeout (pid=%s, url=%s)",
            _process.pid,
            PRIORS_SERVER_URL,
        )
    else:
        manager_logger.error(
            "Priors backend exited before becoming healthy (pid=%s, exit_code=%s, url=%s)",
            _process.pid,
            exit_code,
            PRIORS_SERVER_URL,
        )


def stop() -> None:
    """Terminate the priors backend child process."""
    global _process
    if _process is None:
        return
    if _process.poll() is not None:
        _process = None
        return

    manager_logger.info("Stopping priors backend (pid=%s)", _process.pid)
    _process.terminate()
    try:
        _process.wait(timeout=PROCESS_TERMINATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        _process.kill()
        _process.wait(timeout=PROCESS_TERMINATE_TIMEOUT)
    finally:
        _process = None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5960)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
