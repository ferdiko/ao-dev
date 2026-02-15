import hashlib
import random
import json
import os
import sys
import importlib
import threading
from ao.common.logger import logger


def hash_input(input_bytes):
    """Hash input for deduplication"""
    if isinstance(input_bytes, bytes):
        return hashlib.sha256(input_bytes).hexdigest()
    else:
        return hashlib.sha256(input_bytes.encode("utf-8")).hexdigest()


def set_seed(node_id: str) -> None:
    """Set the seed based on the node_id."""
    seed = int(hashlib.sha256(node_id.encode()).hexdigest(), 16) % (2**32)
    random.seed(seed)


def is_valid_mod(mod_name: str):
    """Checks if one could import this module."""
    try:
        return importlib.util.find_spec(mod_name) is not None
    except:
        return False


def get_module_file_path(module_name: str) -> str | None:
    """
    Get the file path for an installed module without importing it.

    This function searches sys.path manually to avoid the side effects of
    importlib.util.find_spec(), which can trigger partial imports and cause
    module initialization issues.

    Args:
        module_name: The module name (e.g., 'google.genai.models')

    Returns:
        The absolute path to the module file, or None if not found
    """
    # Convert module name to file path components
    # e.g., 'google.genai.models' -> ['google', 'genai', 'models']
    parts = module_name.split(".")

    # Search each directory in sys.path
    for base_path in sys.path:
        if not base_path or not os.path.isdir(base_path):
            continue

        # Build the full path by traversing the package hierarchy
        current_path = base_path
        for part in parts:
            current_path = os.path.join(current_path, part)

        # Check if it's a package (has __init__.py)
        init_path = os.path.join(current_path, "__init__.py")
        if os.path.exists(init_path):
            return os.path.abspath(init_path)

        # Check if it's a module (.py file)
        module_path = current_path + ".py"
        if os.path.exists(module_path):
            return os.path.abspath(module_path)

    return None


# ==============================================================================
# Communication with server.
# ==============================================================================

# Global lock for thread-safe server communication
_server_lock = threading.Lock()


def send_to_server(msg):
    """Thread-safe send message to server (no response expected)."""
    from ao.runner.context_manager import server_file

    if isinstance(msg, dict):
        msg = json.dumps(msg) + "\n"
    elif isinstance(msg, str) and msg[-1] != "\n":
        msg += "\n"
    with _server_lock:
        server_file.write(msg)
        server_file.flush()


def send_to_server_and_receive(msg, timeout=30):
    """Thread-safe send message to server and receive response.

    The listener thread in AgentRunner reads all incoming messages from the socket
    and routes non-control messages (like session_id responses) to a response queue.
    This function sends a message and then waits for the response from that queue.
    """
    from ao.runner.context_manager import server_file, response_queue

    if isinstance(msg, dict):
        msg = json.dumps(msg) + "\n"
    elif isinstance(msg, str) and msg[-1] != "\n":
        msg += "\n"

    with _server_lock:
        logger.debug(f"[send_to_server_and_receive] Sending: {msg[:200]}")
        server_file.write(msg)
        server_file.flush()

    # Wait for response from the queue (populated by listener thread)
    try:
        response = response_queue.get(timeout=timeout)
        logger.debug(f"[send_to_server_and_receive] Received from queue: {response}")
        return response
    except Exception as e:
        logger.error(f"[send_to_server_and_receive] Timeout or error waiting for response: {e}")
        raise


# ===============================================
# Helpers for writing attachments to disk.
# ===============================================
def stream_hash(stream):
    """Compute SHA-256 hash of a binary stream (reads full content into memory)."""
    content = stream.read()
    stream.seek(0)
    return hashlib.sha256(content).hexdigest()


def save_io_stream(stream, filename, dest_dir):
    """
    Save stream to dest_dir/filename. If filename already exists, find new unique one.
    """
    stream.seek(0)
    desired_path = os.path.join(dest_dir, filename)
    if not os.path.exists(desired_path):
        # No conflict, write directly
        with open(desired_path, "wb") as f:
            f.write(stream.read())
        stream.seek(0)
        return desired_path

    # Different content, find a unique name
    base, ext = os.path.splitext(filename)
    counter = 1
    while True:
        new_filename = f"{base}_{counter}{ext}"
        new_path = os.path.join(dest_dir, new_filename)
        if not os.path.exists(new_path):
            with open(new_path, "wb") as f:
                f.write(stream.read())
            stream.seek(0)
            return new_path

        counter += 1
