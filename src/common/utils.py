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

# Per-request response routing: each send_to_server_and_receive call gets a
# unique request_id. The listener thread calls route_response() to deliver
# the response to the correct waiting thread via its Event.
_pending_requests: dict = {}   # request_id -> threading.Event
_pending_responses: dict = {}  # request_id -> response dict
_pending_lock = threading.Lock()


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
    """Thread-safe send message to server and receive the matching response.

    Attaches a request_id to the message. The server echoes it back, and
    route_response() delivers it to this thread's Event.
    """
    import uuid
    from ao.runner.context_manager import server_file

    request_id = str(uuid.uuid4())
    if isinstance(msg, dict):
        msg["request_id"] = request_id
        msg = json.dumps(msg) + "\n"

    event = threading.Event()
    with _pending_lock:
        _pending_requests[request_id] = event

    with _server_lock:
        logger.debug(f"[send_to_server_and_receive] Sending: {msg[:200]}")
        server_file.write(msg)
        server_file.flush()

    try:
        if not event.wait(timeout=timeout):
            raise TimeoutError(f"No response within {timeout}s for request {request_id}")
        with _pending_lock:
            return _pending_responses.pop(request_id)
    finally:
        with _pending_lock:
            _pending_requests.pop(request_id, None)
            _pending_responses.pop(request_id, None)



def route_response(msg):
    """Route an incoming response to the correct waiting thread by request_id.

    Called by the listener thread. Returns True if matched, False otherwise.
    """
    request_id = msg.get("request_id")
    if request_id:
        with _pending_lock:
            event = _pending_requests.get(request_id)
            if event:
                _pending_responses[request_id] = msg
                event.set()
                return True
    return False


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
