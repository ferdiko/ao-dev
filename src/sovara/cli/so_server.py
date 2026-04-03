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
import json
from argparse import ArgumentParser

from sovara.common.logger import logger, create_file_logger

from sovara.common.constants import (
    MAIN_SERVER_LOG,
    PRIORS_SERVER_LOG,
    INFERENCE_SERVER_LOG,
    MAIN_SERVER_STARTUP_LOCK,
    HOST,
    PORT,
    SHUTDOWN_WAIT,
)

# Create file logger for server startup timing (only used in _serve command)
_server_logger = create_file_logger(MAIN_SERVER_LOG)
_STARTUP_LOCK_MAX_AGE_SECONDS = 30


def _truncate_log_file(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w"):
        pass


def _clear_server_logs() -> None:
    for log_path in (MAIN_SERVER_LOG, PRIORS_SERVER_LOG, INFERENCE_SERVER_LOG):
        _truncate_log_file(log_path)


def _clear_priors_caches() -> None:
    from sovara.server.database_manager import DB

    DB.clear_all_prefix_cache()
    DB.clear_all_retrieval_cache()


def _stop_child_servers() -> None:
    from sovara.server.graph_analysis import inference_server

    inference_server.stop()


def _release_startup_lock() -> None:
    try:
        os.remove(MAIN_SERVER_STARTUP_LOCK)
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning(f"Could not remove startup lock {MAIN_SERVER_STARTUP_LOCK}: {exc}")


def _startup_lock_is_fresh(max_age_seconds: int = _STARTUP_LOCK_MAX_AGE_SECONDS) -> bool:
    if not os.path.exists(MAIN_SERVER_STARTUP_LOCK):
        return False
    try:
        age = time.time() - os.path.getmtime(MAIN_SERVER_STARTUP_LOCK)
    except OSError:
        return False
    if age <= max_age_seconds:
        return True
    _release_startup_lock()
    return False


def _acquire_startup_lock() -> bool:
    while True:
        try:
            fd = os.open(MAIN_SERVER_STARTUP_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _startup_lock_is_fresh():
                return False
            continue
        try:
            payload = {
                "pid": os.getpid(),
                "created_at": time.time(),
                "python_executable": sys.executable,
            }
            os.write(fd, json.dumps(payload).encode("utf-8"))
        finally:
            os.close(fd)
        return True


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


def launch_daemon_server() -> bool:
    """Launch the main server as a detached daemon process."""
    if not _acquire_startup_lock():
        logger.info("Main server startup already in progress.")
        return False
    os.makedirs(os.path.dirname(MAIN_SERVER_LOG), exist_ok=True)

    try:
        with open(MAIN_SERVER_LOG, "a+") as log_f:
            subprocess.Popen(
                [sys.executable, "-m", "sovara.cli.so_server", "_serve"],
                close_fds=True,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=subprocess.STDOUT,
            )
    except Exception:
        _release_startup_lock()
        raise
    return True


def server_command_parser():
    parser = ArgumentParser(
        usage="so-server {start, stop, restart, clear, logs, priors-logs, infer-logs, clear-logs, _clear_cache}",
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
            "priors-logs",
            "infer-logs",
            "clear-logs",
            "_clear_cache",
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
        if launch_daemon_server():
            logger.info("Main server started.")
        return

    elif args.command == "stop":
        stopped_main = _server_http_request("POST", "/ui/shutdown")
        time.sleep(SHUTDOWN_WAIT)
        _stop_child_servers()
        if not stopped_main:
            logger.warning("No running server found.")
            sys.exit(1)
        logger.info("Main server stop signal sent.")

    elif args.command == "restart":
        _server_http_request("POST", "/ui/shutdown")
        time.sleep(SHUTDOWN_WAIT)
        _stop_child_servers()
        try:
            _clear_server_logs()
        except Exception as e:
            logger.error(f"Error clearing server logs: {e}")
        if launch_daemon_server():
            logger.info("Main server restarted.")
        return

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
        try:
            with open(INFERENCE_SERVER_LOG, "r") as log_file:
                print(log_file.read(), end="")
        except FileNotFoundError:
            logger.error(f"Log file not found at {INFERENCE_SERVER_LOG}")
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
        return

    elif args.command == "priors-logs":
        try:
            with open(PRIORS_SERVER_LOG, "r") as log_file:
                print(log_file.read(), end="")
        except FileNotFoundError:
            logger.error(f"Log file not found at {PRIORS_SERVER_LOG}")
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
        return

    elif args.command == "clear-logs":
        try:
            _clear_server_logs()
        except Exception as e:
            logger.error(f"Error clearing server logs: {e}")
        logger.info("Server log files cleared.")
        return

    elif args.command == "_clear_cache":
        try:
            _clear_priors_caches()
        except Exception as e:
            logger.error(f"Error clearing priors caches: {e}")
            raise
        logger.info("Priors cache entries cleared.")
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
        try:
            uv_server.run()
        finally:
            try:
                _stop_child_servers()
            except Exception as exc:
                _server_logger.warning(f"Could not stop child servers during shutdown: {exc}")
            _release_startup_lock()


def main():
    parser = server_command_parser()
    args = parser.parse_args()
    execute_server_command(args)


if __name__ == "__main__":
    main()
