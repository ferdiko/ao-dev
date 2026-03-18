import hashlib
import random
import os
import sys
import importlib
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
    """Get the file path for an installed module without importing it."""
    parts = module_name.split(".")
    for base_path in sys.path:
        if not base_path or not os.path.isdir(base_path):
            continue
        current_path = base_path
        for part in parts:
            current_path = os.path.join(current_path, part)
        init_path = os.path.join(current_path, "__init__.py")
        if os.path.exists(init_path):
            return os.path.abspath(init_path)
        module_path = current_path + ".py"
        if os.path.exists(module_path):
            return os.path.abspath(module_path)
    return None


# ==============================================================================
# Communication with server via HTTP.
# ==============================================================================

_http_client = None
_server_base_url = None


def set_server_url(url: str) -> None:
    """Set the server base URL for HTTP communication."""
    global _server_base_url, _http_client
    _server_base_url = url
    # Reset client so it picks up the new URL
    _http_client = None


def _get_http_client():
    """Lazy-initialize and return the shared httpx client."""
    global _http_client
    if _http_client is None:
        import httpx
        _http_client = httpx.Client(timeout=30.0)
    return _http_client


def http_post(endpoint: str, data: dict) -> dict:
    """POST JSON to the server and return the response dict.

    Raises on failure -- callers that are best-effort should catch exceptions.
    """
    if not _server_base_url:
        raise RuntimeError("Server URL not set")
    client = _get_http_client()
    resp = client.post(f"{_server_base_url}{endpoint}", json=data)
    resp.raise_for_status()
    return resp.json()


# ===============================================
# Helpers for writing attachments to disk.
# ===============================================
def stream_hash(stream):
    """Compute SHA-256 hash of a binary stream (reads full content into memory)."""
    content = stream.read()
    stream.seek(0)
    return hashlib.sha256(content).hexdigest()


def save_io_stream(stream, filename, dest_dir):
    """Save stream to dest_dir/filename. If filename already exists, find new unique one."""
    stream.seek(0)
    desired_path = os.path.join(dest_dir, filename)
    if not os.path.exists(desired_path):
        with open(desired_path, "wb") as f:
            f.write(stream.read())
        stream.seek(0)
        return desired_path

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
