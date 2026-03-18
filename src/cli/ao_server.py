import sys
import os
import time as _time

_import_start = _time.time()

# Add current directory to path to import modules directly
current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import socket
import time
import subprocess
from argparse import ArgumentParser

from ao.common.logger import logger, create_file_logger

from ao.common.constants import (
    MAIN_SERVER_LOG,
    HOST,
    PORT,
    SOCKET_TIMEOUT,
    SHUTDOWN_WAIT,
)

from ao.server.main_server import MainServer, send_json

# Create file logger for server startup timing (only used in _serve command)
_server_logger = create_file_logger(MAIN_SERVER_LOG)


def launch_daemon_server() -> None:
    """
    Launch the main server as a detached daemon process with proper stdio handling.
    """
    # Ensure log directory exists
    os.makedirs(os.path.dirname(MAIN_SERVER_LOG), exist_ok=True)

    # Open log file for the daemon (all logs go to main_server.log)
    with open(MAIN_SERVER_LOG, "a+") as log_f:
        subprocess.Popen(
            [sys.executable, "-m", "ao.cli.ao_server", "_serve"],
            close_fds=True,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,  # Combine stderr with stdout
        )


def server_command_parser():
    parser = ArgumentParser(
        usage="ao-server {start, stop, restart, clear, logs, clear-logs}",
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
            "clear-logs",
            "_serve",
        ],
        help="The command to execute for the server.",
    )
    return parser


def execute_server_command(args):
    if args.command == "start":
        # If server is already running, do not start another
        try:
            socket.create_connection((HOST, PORT), timeout=SOCKET_TIMEOUT).close()
            logger.info("Main server is already running.")
            return
        except Exception:
            pass
        # Launch the server as a detached background process (POSIX)
        launch_daemon_server()
        logger.info("Main server started.")

    elif args.command == "stop":
        # Connect to the server and send a shutdown command
        try:
            sock = socket.create_connection((HOST, PORT), timeout=SOCKET_TIMEOUT)
            handshake = {"type": "hello", "role": "admin", "script": "stopper"}
            send_json(sock, handshake)
            send_json(sock, {"type": "shutdown"})
            sock.close()
            logger.info("Main server stop signal sent.")
        except Exception:
            logger.warning("No running server found.")
            sys.exit(1)

    elif args.command == "restart":
        # Stop the server if running
        try:
            sock = socket.create_connection((HOST, PORT), timeout=SOCKET_TIMEOUT)
            handshake = {"type": "hello", "role": "admin", "script": "restarter"}
            send_json(sock, handshake)
            send_json(sock, {"type": "shutdown"})
            sock.close()
            logger.info("Main server stop signal sent (for restart). Waiting for shutdown...")
            time.sleep(SHUTDOWN_WAIT)
        except Exception:
            logger.info("No running server found. Proceeding to start.")
        # Clear log file before starting fresh
        try:
            with open(MAIN_SERVER_LOG, "w"):
                pass
        except Exception:
            pass
        # Start the server
        launch_daemon_server()
        logger.info("Main server restarted.")

    elif args.command == "clear":
        confirm = input("This will delete all experiments and LLM call data. Continue? [y/N] ")
        if confirm.strip().lower() != "y":
            print("Aborted.")
            return
        try:
            sock = socket.create_connection((HOST, PORT), timeout=SOCKET_TIMEOUT)
            handshake = {"type": "hello", "role": "admin", "script": "clearer"}
            send_json(sock, handshake)
            send_json(sock, {"type": "clear"})
            sock.close()
            logger.info("All data cleared.")
        except Exception:
            logger.warning("No running server found.")
            sys.exit(1)
        return

    elif args.command == "logs":
        # Print the contents of the develop server log file
        try:
            with open(MAIN_SERVER_LOG, "r") as log_file:
                print(log_file.read(), end="")
        except FileNotFoundError:
            logger.error(f"Log file not found at {MAIN_SERVER_LOG}")
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
        return

    elif args.command == "clear-logs":
        # Clear server log file
        try:
            os.makedirs(os.path.dirname(MAIN_SERVER_LOG), exist_ok=True)
            with open(MAIN_SERVER_LOG, "w"):
                pass
        except Exception as e:
            logger.error(f"Error clearing log file {MAIN_SERVER_LOG}: {e}")
        logger.info("Server log file cleared.")
        return

    elif args.command == "_serve":
        # Internal: run the server loop (not meant to be called by users directly)
        _server_logger.info(f"Imports completed in {_time.time() - _import_start:.2f}s")

        # Save Python executable path to config for VS Code extension to use
        from ao.common.constants import AO_CONFIG
        from ao.common.config import Config

        try:
            config = Config.from_yaml_file(AO_CONFIG)
            if config.python_executable != sys.executable:
                config.python_executable = sys.executable
                config.to_yaml_file(AO_CONFIG)
                _server_logger.info(f"Saved python_executable: {sys.executable}")
        except Exception as e:
            _server_logger.warning(f"Could not save python_executable: {e}")

        _start = _time.time()
        server = MainServer()
        _server_logger.info(f"MainServer created in {_time.time() - _start:.2f}s")
        server.run_server()


def main():
    parser = server_command_parser()
    args = parser.parse_args()
    execute_server_command(args)


if __name__ == "__main__":
    main()
