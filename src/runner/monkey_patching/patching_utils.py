import inspect
import os
import re
import threading
import traceback
from collections import defaultdict
from ao.runner.context_manager import get_session_id
from ao.common.constants import CERTAINTY_UNKNOWN
from ao.common.utils import send_to_server, get_node_label, get_raw_model_name
from ao.common.logger import logger


# ===========================================================
# Generic wrappers for caching and server notification
# ===========================================================

# str -> {str -> set(str)}
# if we add a -> b, we go through every element. If a is in the set, we add b to the
_graph_reachable_set = defaultdict(lambda: defaultdict(set))
_graph_lock = threading.Lock()

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


def send_graph_node_and_edges(node_id, input_dict, output_obj, source_node_ids, api_type, stack_trace=None):
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

    # Store input for this node (needed for containment checks)
    from ao.runner.string_matching import store_input_strings, output_contained_in_input
    store_input_strings(session_id, node_id, input_dict, api_type)

    # Update reachability and filter redundant edges under lock
    with _graph_lock:
        for source_node_id in source_node_ids:
            _graph_reachable_set[session_id][source_node_id].add(node_id)

        for reachable_by_a in _graph_reachable_set[session_id].values():
            if any(source_node_id in reachable_by_a for source_node_id in source_node_ids):
                reachable_by_a.add(node_id)

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
