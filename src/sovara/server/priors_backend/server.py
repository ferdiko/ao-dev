"""Priors backend child service process manager and entrypoint."""

import argparse
import os
import subprocess
import sys
from typing import Optional
from urllib.parse import urlparse

from sovara.common.constants import PRIORS_SERVER_LOG, PRIORS_SERVER_URL, PROCESS_TERMINATE_TIMEOUT
from sovara.server.priors_backend.app import create_app

app = create_app()

_process: Optional[subprocess.Popen] = None


def _resolve_bind_host_port() -> tuple[str, int]:
    parsed = urlparse(PRIORS_SERVER_URL)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port is not None:
        return host, parsed.port
    if parsed.scheme == "https":
        return host, 443
    return host, 80


def start() -> None:
    """Spawn the priors backend as a child process."""
    global _process
    if _process is not None and _process.poll() is None:
        return

    host, port = _resolve_bind_host_port()
    os.makedirs(os.path.dirname(PRIORS_SERVER_LOG), exist_ok=True)
    log_f = open(PRIORS_SERVER_LOG, "a")
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


def stop() -> None:
    """Terminate the priors backend child process."""
    global _process
    if _process is None:
        return
    if _process.poll() is not None:
        _process = None
        return

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
