import sys
import os
import time as _time

_import_start = _time.time()

# Ensure the parent of the package is importable when running the module directly.
package_parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if package_parent not in sys.path:
    sys.path.insert(0, package_parent)

import time
import subprocess
from argparse import ArgumentParser

from sovara.common.logger import logger, create_file_logger

from sovara.common.constants import (
    MAIN_SERVER_LOG,
    HOST,
    PORT,
    SHUTDOWN_WAIT,
)

# Create file logger for server startup timing (only used in _serve command)
_server_logger = create_file_logger(MAIN_SERVER_LOG)


def _server_http_request(method: str, path: str, timeout: float = 2.0) -> bool:
    """Make an HTTP request to the server. Returns True if successful."""
    import httpx
    try:
        url = f"http://{HOST}:{PORT}{path}"
        with httpx.Client(timeout=timeout) as client:
            if method == "GET":
                resp = client.get(url)
            else:
                resp = client.post(url)
            return resp.status_code == 200
    except Exception:
        return False


def _is_server_running() -> bool:
    """Check if the server is running via health endpoint."""
    return _server_http_request("GET", "/health")


def launch_daemon_server() -> None:
    """Launch the main server as a detached daemon process."""
    os.makedirs(os.path.dirname(MAIN_SERVER_LOG), exist_ok=True)

    with open(MAIN_SERVER_LOG, "a+") as log_f:
        subprocess.Popen(
            [sys.executable, "-m", "sovara.cli.so_server", "_serve"],
            close_fds=True,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )


def server_command_parser():
    parser = ArgumentParser(
        usage="so-server {start, stop, restart, clear, logs, clear-logs}",
        description="Server utilities.",
        allow_abbrev=False,
    )

    parser.add_argument(
        "command",
        choices=[
            "start",
            "stop",
            "restart",
            "clear",
            "logs",
            "infer-logs",
            "clear-logs",
            "_serve",
        ],
        help="The command to execute for the server.",
    )
    return parser


def execute_server_command(args):
    if args.command == "start":
        if _is_server_running():
            logger.info("Main server is already running.")
            return
        launch_daemon_server()
        logger.info("Main server started.")

    elif args.command == "stop":
        if not _server_http_request("POST", "/ui/shutdown"):
            logger.warning("No running server found.")
            sys.exit(1)
        logger.info("Main server stop signal sent.")

    elif args.command == "restart":
        _server_http_request("POST", "/ui/shutdown")
        time.sleep(SHUTDOWN_WAIT)
        # Clear log file before starting fresh
        try:
            with open(MAIN_SERVER_LOG, "w"):
                pass
        except Exception:
            pass
        launch_daemon_server()
        logger.info("Main server restarted.")

    elif args.command == "clear":
        if not _server_http_request("POST", "/ui/clear"):
            logger.warning("No running server found.")
            sys.exit(1)
        logger.info("Main server clear signal sent.")

    elif args.command == "logs":
        try:
            with open(MAIN_SERVER_LOG, "r") as log_file:
                print(log_file.read(), end="")
        except FileNotFoundError:
            logger.error(f"Log file not found at {MAIN_SERVER_LOG}")
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
        return

    elif args.command == "infer-logs":
        from sovara.common.constants import INFERENCE_SERVER_LOG
        try:
            with open(INFERENCE_SERVER_LOG, "r") as log_file:
                print(log_file.read(), end="")
        except FileNotFoundError:
            logger.error(f"Log file not found at {INFERENCE_SERVER_LOG}")
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
        return

    elif args.command == "clear-logs":
        try:
            os.makedirs(os.path.dirname(MAIN_SERVER_LOG), exist_ok=True)
            with open(MAIN_SERVER_LOG, "w"):
                pass
        except Exception as e:
            logger.error(f"Error clearing log file {MAIN_SERVER_LOG}: {e}")
        logger.info("Server log file cleared.")
        return

    elif args.command == "_serve":
        _server_logger.info(f"Imports completed in {_time.time() - _import_start:.2f}s")

        # Save Python executable path to config for VS Code extension to use
        from sovara.common.constants import SOVARA_CONFIG
        from sovara.common.config import Config

        try:
            config = Config.from_yaml_file(SOVARA_CONFIG)
            if config.python_executable != sys.executable:
                config.python_executable = sys.executable
                config.to_yaml_file(SOVARA_CONFIG)
                _server_logger.info(f"Saved python_executable: {sys.executable}")
        except Exception as e:
            _server_logger.warning(f"Could not save python_executable: {e}")

        import uvicorn
        from sovara.server.app import create_app

        _start = _time.time()
        app = create_app()
        _server_logger.info(f"FastAPI app created in {_time.time() - _start:.2f}s")

        # Use Config+Server instead of uvicorn.run() so we can set
        # server.should_exit = True for clean programmatic shutdown.
        uv_config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
        uv_server = uvicorn.Server(uv_config)

        # Store reference on app so lifespan can wire it into ServerState.
        app.state.uvicorn_server = uv_server
        uv_server.run()


def main():
    parser = server_command_parser()
    args = parser.parse_args()
    execute_server_command(args)


if __name__ == "__main__":
    main()
