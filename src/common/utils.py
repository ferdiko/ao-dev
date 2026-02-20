import hashlib
import random
import json
import os
import re
import sys
import importlib
from pathlib import Path
import threading
from typing import Optional, Union, Dict, Any
from ao.common.constants import (
    COMPILED_ENDPOINT_PATTERNS,
    COMPILED_URL_PATTERN_TO_NODE_NAME,
    NO_LABEL,
    COMPILED_MODEL_NAME_PATTERNS,
    INVALID_LABEL_CHARS,
)
from ao.common.logger import logger


# ==============================================================================
# Model and tool name extraction
# ==============================================================================
def _extract_model_from_body(input_dict: Dict[str, Any], api_type: str) -> Optional[str]:
    """
    Extract model name from request body/params (API-specific).
    Returns None if extraction fails.
    """
    try:
        if api_type == "requests.Session.send":
            body = input_dict["request"].body
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            return json.loads(body)["model"]

        elif api_type in ["httpx.Client.send", "httpx.AsyncClient.send"]:
            content = input_dict["request"].content.decode("utf-8")
            return json.loads(content)["model"]

        elif api_type == "genai.BaseApiClient.async_request":
            if "model" in input_dict.get("request_dict", {}):
                return input_dict["request_dict"]["model"]
            return None

        elif api_type == "MCP.ClientSession.send_request":
            return input_dict["request"].root.params.name

    except (KeyError, json.JSONDecodeError, UnicodeDecodeError, AttributeError, TypeError):
        pass

    return None


def _extract_name_from_url(input_dict: Dict[str, Any], api_type: str) -> Optional[str]:
    """
    Extract model name from URL path or known URL patterns.
    Returns None if extraction fails.
    """
    try:
        # Get URL based on API type
        if api_type == "requests.Session.send":
            url = str(input_dict["request"].url)
            path = input_dict["request"].path_url
        elif api_type in ["httpx.Client.send", "httpx.AsyncClient.send"]:
            url = str(input_dict["request"].url)
            path = input_dict["request"].url.path
        elif api_type == "genai.BaseApiClient.async_request":
            path = input_dict.get("path", "")
            url = path  # genai doesn't have full URL
        elif api_type == "MCP.ClientSession.send_request":
            # MCP doesn't have URL-based fallback traditionally, but we can try
            return None
        else:
            return None

        # Try regex pattern for /models/xxx:<path> or models/xxx:<path>
        match = re.search(r"/?models/([^/:]+)", path)
        if match:
            return match.group(1)

        # Try known URL patterns (tools like Serper, Brave, etc.)
        for pattern, name in COMPILED_URL_PATTERN_TO_NODE_NAME:
            if pattern.search(url):
                return name

        # Last resort: return the path itself
        if url:
            return url

    except (AttributeError, KeyError, TypeError):
        pass

    return None


def _clean_model_name(name: str) -> str:
    """
    Clean raw model name by applying extraction patterns.
    E.g., "meta-llama/Llama-3-8B" -> "Llama-3-8B"
    """
    if not name:
        return name

    # HuggingFace format: org/model-name -> extract model-name
    if "/" in name:
        name = name.rsplit("/", 1)[-1]

    return name


def _sanitize_for_display(name: str) -> str:
    """
    Sanitize model name for display as node label.
    Truncation is handled in the VSCode extension (CustomNode.tsx).
    """
    from urllib.parse import urlparse

    if not name:
        return NO_LABEL

    # Check for exact match against known model patterns first
    for pattern, clean_name in COMPILED_MODEL_NAME_PATTERNS:
        if pattern.match(name):
            return clean_name

    parsed_url = urlparse(name)
    if parsed_url.scheme and parsed_url.netloc:
        name = parsed_url.hostname + parsed_url.path
    else:
        # this is not a valid URL, so we treat it as a model name/tool name
        # Convert hyphens between digits to dots (version numbers like 2-5 -> 2.5)
        name = re.sub(r"(\d)-(?=\d)", r"\1.", name)

        # Replace underscores and remaining hyphens with spaces, then title case
        name = name.replace("_", " ").replace("-", " ").title()

    # Check for invalid characters that indicate malformed input
    if any(c in INVALID_LABEL_CHARS for c in name):
        return NO_LABEL

    return name


def get_raw_model_name(input_dict: Dict[str, Any], api_type: str) -> str:
    """
    Extract raw model/tool name from request (for caching).

    Tries body/params first, then URL fallback.
    Returns NO_LABEL if extraction fails.
    """
    raw_name = _extract_model_from_body(input_dict, api_type)
    if not raw_name:
        raw_name = _extract_name_from_url(input_dict, api_type)
    return raw_name or NO_LABEL


def get_node_label(input_dict: Dict[str, Any], api_type: str) -> str:
    """
    Extract and sanitize model/tool name for display as node label.

    1. Extract from body/params
    2. Clean HuggingFace-style names (org/model -> model)
    3. Fall back to URL extraction if body fails
    4. Sanitize for display
    """
    raw_name = _extract_model_from_body(input_dict, api_type)
    if raw_name:
        raw_name = _clean_model_name(raw_name)
    else:
        raw_name = _extract_name_from_url(input_dict, api_type)

    return _sanitize_for_display(raw_name) if raw_name else NO_LABEL


def is_whitelisted_endpoint(url: str, path: str) -> bool:
    """Check if a URL and path match any of the whitelist (url_regex, path_regex) tuples."""
    for url_pattern, path_pattern in COMPILED_ENDPOINT_PATTERNS:
        if url_pattern.search(url) and path_pattern.search(path):
            return True
    return False


def get_node_name_for_url(url: str) -> Optional[str]:
    """Return the display name for a URL if it matches any pattern, else None."""
    for pattern, name in COMPILED_URL_PATTERN_TO_NODE_NAME:
        if pattern.search(url):
            return name
    return None


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



# ==============================================================================
# We try to derive the project root relative to the user working directory.
# All of the below is implementing this heuristic search.
# ==============================================================================
def derive_project_root(start: str | None = None) -> str:
    """
    Walk upward from current working directory to infer a Python project root.

    Heuristics (in order of strength):
      1) If the directory contains project/repo markers (pyproject.toml, .git, etc.), STOP and return it.
      2) If a parent directory name cannot be part of a Python module path (not an identifier), STOP at that directory.
      3) If we encounter common non-project anchor dirs (~/Documents, ~/Downloads, /usr, C:\\Windows, /Applications, etc.),
         DO NOT go above them; return the last "good" directory below.
      4) If we detect we're about to cross a virtualenv boundary, return the last good directory below.
      5) If we hit the filesystem root without any better signal, return the last good directory we saw.

    "Last good directory" = the most recent directory we visited that could plausibly be part of an importable path
    (i.e., its name is a valid identifier or it's a top-level candidate that doesn't obviously look like an anchor).

    Returns:
        String path to the inferred project root.
    """
    cur = _normalize_start(start)
    last_good = cur

    for p in _walk_up(cur):
        # Strong signal: repo/project markers at this directory
        if _has_project_markers(p) or _has_src_layout_hint(p):
            return str(p)

        # If this segment cannot be in a Python dotted path, don't go above it.
        if not _segment_is_import_safe(p):
            return str(p)

        # If this is a known "anchor" (Documents, Downloads, Program Files, /usr, etc.),
        # don't float above it; the project likely lives below.
        if _is_common_non_project_dir(p):
            return str(last_good)

        # Don't float above a virtualenv boundary (if start happened to be inside one).
        if _looks_like_virtualenv_root(p):
            return str(last_good)

        # If nothing special, this remains a reasonable candidate.
        last_good = p

    # We reached the OS root without a decisive marker.
    return str(last_good)


def _normalize_start(start: Optional[Union[str, os.PathLike]]) -> Path:
    if start is None:
        start = Path.cwd()
    p = Path(start)
    if p.is_file():
        p = p.parent
    return p.resolve()


def _walk_up(start_dir: Path):
    """Yield start_dir, then its parents up to the filesystem root."""
    p = start_dir
    while True:
        yield p
        if p.parent == p:
            break  # reached filesystem root
        p = p.parent


def _has_project_markers(p: Path) -> bool:
    """
    Things that strongly indicate "this is a project/repo root".
    You can extend this list to fit your org/monorepo conventions.
    """
    files = {
        "pyproject.toml",
        "poetry.lock",
        "Pipfile",
        "requirements.txt",
        "setup.cfg",
        "setup.py",
        "tox.ini",
        ".editorconfig",
        ".flake8",
        "mypy.ini",
        "README.md",
        "README.rst",
    }
    dirs = {
        ".git",
        ".hg",
        ".svn",
        ".idea",  # JetBrains project
        ".vscode",  # VS Code project
    }
    return any((p / f).exists() for f in files) or any((p / d).is_dir() for d in dirs)



def _has_src_layout_hint(p: Path) -> bool:
    """
    Mild positive signal: a 'src/' directory that appears to contain importable packages.
    We don't require __init__.py (PEP 420 namespaces exist). We only treat this as a hint,
    not as strong as explicit markers—so it's folded into `_has_project_markers`-like logic.
    """
    src = p / "src"
    if not src.is_dir():
        return False

    # Does src contain at least one directory that looks like a Python package segment?
    for child in src.iterdir():
        if child.is_dir() and _name_looks_like_package(child.name):
            return True
    return False


def _segment_is_import_safe(p: Path) -> bool:
    """
    A directory name that cannot be a valid Python identifier cannot be part of a dotted module path.
    If it's not import-safe, we don't go above it (we stop at it).
    """
    name = p.name
    # At filesystem root, name may be '' (POSIX) or 'C:\\' (Windows); treat as non-import-segment.
    if name == "" or p.parent == p:
        return False
    return name.isidentifier()


def _name_looks_like_package(name: str) -> bool:
    """
    Heuristic for a directory that *could* be an importable package:
    - valid identifier (letters, digits, underscore; not starting with digit)
    """
    return name.isidentifier()


def _looks_like_virtualenv_root(p: Path) -> bool:
    """
    Common virtualenv layouts:
      - <venv>/bin/activate      (POSIX)
      - <venv>/Scripts/activate  (Windows)
    Also many people name the dir 'venv', '.venv', 'env', '.env'
    """
    if p.name in {"venv", ".venv", "env", ".env"}:
        return True
    if (p / "bin" / "activate").is_file():
        return True
    if (p / "Scripts" / "activate").is_file():
        return True
    return False


def _is_common_non_project_dir(p: Path) -> bool:
    """
    Directories that are very often "anchors" above real projects.
    We avoid floating above these; instead we return the last good dir below them.
    This is conservative and OS-aware.
    """
    # Normalize case on Windows to avoid case-sensitivity surprises.
    name_lower = p.name.lower()

    home = Path.home()
    try:
        in_home = home in p.parents or p == home
    except Exception:
        in_home = False

    # --- macOS / Linux-ish anchors ---
    posix_anchors = {
        "applications",  # macOS
        "library",  # macOS / shared
        "system",  # macOS
        "usr",
        "bin",
        "sbin",
        "etc",
        "var",
        "opt",
        "proc",
        "dev",
    }
    posix_home_anchors = {
        "documents",
        "downloads",
        "desktop",
        "music",
        "movies",
        "pictures",
        "public",
        "library",  # user's Library on macOS
    }

    # --- Windows anchors ---
    windows_anchors = {
        "windows",
        "program files",
        "program files (x86)",
        "programdata",
        "intel",
        "nvidia corporation",
    }
    windows_home_anchors = {
        "documents",
        "downloads",
        "desktop",
        "pictures",
        "music",
        "videos",
        "onedrive",
        "dropbox",
    }

    # Filesystem root? Treat as an anchor we don't climb past.
    if p.parent == p:
        return True

    if os.name == "nt":
        if name_lower in windows_anchors:
            return True
        if in_home and name_lower in windows_home_anchors:
            return True
        # Example: C:\Users\<me>\Documents — stop at Documents
        if in_home and name_lower == "users":
            return True
    else:
        if name_lower in posix_anchors:
            return True
        if in_home and name_lower in posix_home_anchors:
            return True

    # Generic cloud-sync / archive / tooling anchors (cross-platform):
    generic_anchors = {
        "icloud drive",
        "google drive",
        "dropbox",
        "box",
        "library",  # often a user-level anchor on macOS
        "applications",  # second chance
    }
    if name_lower in generic_anchors:
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
