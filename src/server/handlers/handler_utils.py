"""Shared utilities for message handlers."""

import json
import socket

from ao.common.logger import create_file_logger
from ao.common.constants import MAIN_SERVER_LOG

logger = create_file_logger(MAIN_SERVER_LOG)


def send_json(conn: socket.socket, msg: dict) -> None:
    """Send a JSON message over a socket connection."""
    try:
        msg_type = msg.get("type", "unknown")
        logger.debug(f"Sent message type: {msg_type}")
        conn.sendall((json.dumps(msg) + "\n").encode("utf-8"))
    except Exception as e:
        logger.error(f"Error sending JSON: {e}")
