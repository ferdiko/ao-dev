import inspect
import json
import os
import re
import traceback
from collections import defaultdict
from typing import Optional, Dict, Any
from ao.runner.context_manager import get_session_id
from ao.common.constants import (
    CERTAINTY_UNKNOWN,
    COMPILED_ENDPOINT_PATTERNS,
    COMPILED_URL_PATTERN_TO_NODE_NAME,
    NO_LABEL,
    COMPILED_MODEL_NAME_PATTERNS,
    INVALID_LABEL_CHARS,
)
from ao.common.utils import send_to_server
from ao.common.logger import logger


# ===========================================================
# Model and tool name extraction
# ===========================================================


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

        elif api_type == "claude_agent_sdk.parse_message":
            # For SDK messages: redacted LLM nodes, tool calls, or text responses
            if input_dict.get("type") == "redacted_llm":
                return "Redacted Reasoning"
            return input_dict.get("tool_name") or input_dict.get("model")

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


# ===========================================================
# Generic wrappers for caching and server notification
# ===========================================================

# str -> {str -> set(str)}
# if we add a -> b, we go through every element. If a is in the set, we add b to the
_graph_reachable_set = defaultdict(lambda: defaultdict(set))


def capture_stack_trace() -> str:
    """Capture the current stack trace, showing only user code.

    Removes ao infrastructure frames:
    - Beginning: everything up to and including ao/runner/agent_runner.py
    - End: everything from and including ao/server/database_manager.py
    - Middle: any frames inside ao-dev/ (unless cwd is ao-dev itself)
    """
    stack_lines = traceback.format_stack()

    # Find the start index: skip frames up to and including agent_runner.py
    start_idx = 0
    for i, line in enumerate(stack_lines):
        if "ao/runner/agent_runner.py" in line or "ao\\runner\\agent_runner.py" in line:
            start_idx = i + 1  # Start after this frame

    # Find the end index: stop before database_manager.py
    end_idx = len(stack_lines)
    for i, line in enumerate(stack_lines):
        if "ao/server/database_manager.py" in line or "ao\\server\\database_manager.py" in line:
            end_idx = i
            break

    # Extract only user code frames
    user_frames = stack_lines[start_idx:end_idx]

    # Filter out ao-dev frames unless we're developing ao-dev itself
    # Split cwd on path separators and check if "ao-dev" is an exact directory name
    cwd = os.getcwd()
    cwd_parts = re.split(r"[/\\]", cwd)
    developing_ao = "ao-dev" in cwd_parts

    if not developing_ao:
        # Filter out any frames from ao-dev directory
        # Match /ao-dev/ or \ao-dev\ as exact directory name
        filtered_frames = []
        for frame in user_frames:
            if "/ao-dev/" not in frame and "\\ao-dev\\" not in frame:
                filtered_frames.append(frame)
        user_frames = filtered_frames

    return "".join(user_frames).rstrip()


def get_input_dict(func, *args, **kwargs):
    # Arguments are normalized to the function's parameter order.
    # func(a=5, b=2) and func(b=2, a=5) will result in same dict.

    # Try to get signature, handling "invalid method signature" error
    sig = None
    try:
        sig = inspect.signature(func)
    except ValueError as e:
        if "invalid method signature" in str(e):
            # This can happen with monkey-patched bound methods
            # Try to get the signature from the unbound method instead
            if hasattr(func, "__self__") and hasattr(func, "__func__"):
                try:
                    # Get the unbound function from the class
                    cls = func.__self__.__class__
                    func_name = func.__name__
                    unbound_func = getattr(cls, func_name)
                    sig = inspect.signature(unbound_func)

                    # For unbound methods, we need to include 'self' in the arguments
                    # when binding, so prepend the bound object as the first argument
                    args = (func.__self__,) + args
                except (AttributeError, TypeError):
                    # If we can't get the unbound signature, re-raise the original error
                    raise e
        else:
            # Re-raise other ValueError exceptions
            raise e

    if sig is None:
        raise ValueError("Could not obtain function signature")

    try:
        bound = sig.bind(*args, **kwargs)
    except TypeError:
        # Many APIs only accept kwargs
        bound = sig.bind(**kwargs)
    bound.apply_defaults()

    input_dict = {}
    for name, value in bound.arguments.items():
        if name == "self":
            continue
        param = sig.parameters[name]
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            input_dict.update(value)  # Flatten the captured extras
        else:
            input_dict[name] = value

    return input_dict


def send_graph_node_and_edges(
    node_id, input_dict, output_obj, source_node_ids, api_type, stack_trace=None
):
    """Send graph node and edge updates to the server."""
    # Use provided stack_trace or capture a new one
    if stack_trace is None:
        stack_trace = capture_stack_trace()

    # Import here to avoid circular import
    from ao.runner.monkey_patching.api_parser import func_kwargs_to_json_str, api_obj_to_json_str

    # Get strings to display in UI.
    input_string, attachments = func_kwargs_to_json_str(input_dict, api_type)
    output_string = api_obj_to_json_str(output_obj, api_type)
    model = get_raw_model_name(input_dict, api_type)
    label = get_node_label(input_dict, api_type)
    session_id = get_session_id()

    for source_node_id in source_node_ids:
        _graph_reachable_set[session_id][source_node_id].add(node_id)

    for reachable_by_a in _graph_reachable_set[session_id].values():
        if any(source_node_id in reachable_by_a for source_node_id in source_node_ids):
            reachable_by_a.add(node_id)

    # Store input for this node (needed for containment checks)
    from ao.runner.string_matching import store_input_strings, output_contained_in_input

    store_input_strings(session_id, node_id, input_dict, api_type)

    # Filter redundant source nodes: if node_b is reachable from node_a and node_a's output
    # is contained in node_b's input, remove node_a (its content already flows through node_b)
    nodes_to_remove = set()
    for node_a in source_node_ids:
        for node_b in source_node_ids:
            if node_a != node_b and node_b in _graph_reachable_set[session_id][node_a]:
                if output_contained_in_input(session_id, node_a, node_b):
                    nodes_to_remove.add(node_a)
    source_node_ids = [n for n in source_node_ids if n not in nodes_to_remove]

    # Send node
    node_msg = {
        "type": "add_node",
        "session_id": session_id,
        "node": {
            "id": node_id,
            "input": input_string,
            "output": output_string,
            "border_color": CERTAINTY_UNKNOWN,
            "label": label,
            "stack_trace": stack_trace,
            "model": model,
            "attachments": attachments,
        },
        "incoming_edges": source_node_ids,
    }

    try:
        send_to_server(node_msg)
    except Exception as e:
        logger.error(f"Failed to send add_node: {e}")
