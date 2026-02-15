"""
API parser for claude_agent_sdk messages.

Handles serialization/deserialization of SDK message data for display in the UI.
Since we intercept at the message parsing level (not HTTP), the data structures
are simpler - just Python dicts representing tool calls and responses.
"""

import json
from typing import Any, Dict, Tuple, List


def func_kwargs_to_json_str_claude_sdk(input_dict: Dict[str, Any]) -> Tuple[str, List[str]]:
    """
    Convert SDK message input to JSON string for display.

    Args:
        input_dict: Contains tool_name, tool_input, tool_use_id (for tools)
                   or type, model (for text responses)

    Returns:
        Tuple of (JSON string with raw/to_show structure, list of attachment IDs)
    """
    # Create the standard format with raw and to_show
    to_show = {}

    if "tool_name" in input_dict:
        to_show["tool"] = input_dict["tool_name"]
        if input_dict.get("tool_input"):
            to_show["input"] = input_dict["tool_input"]
    elif input_dict.get("type") == "assistant_response":
        to_show["type"] = "Assistant Response"
        if input_dict.get("model"):
            to_show["model"] = input_dict["model"]

    result = {
        "raw": input_dict,
        "to_show": to_show,
    }

    return json.dumps(result, indent=2, default=str), []


def api_obj_to_json_str_claude_sdk(obj: Any) -> str:
    """
    Convert SDK message output to JSON string for display.

    Args:
        obj: Output dict containing tool result or text response

    Returns:
        JSON string with raw/to_show structure
    """
    if not isinstance(obj, dict):
        obj = {"value": str(obj)}

    # Create the standard format
    to_show = {}

    if "tool_name" in obj:
        to_show["tool"] = obj["tool_name"]
        if obj.get("tool_input"):
            to_show["input"] = obj["tool_input"]
    elif "text" in obj:
        to_show["response"] = obj["text"]

    result = {
        "raw": obj,
        "to_show": to_show,
    }

    return json.dumps(result, indent=2, default=str)


def json_str_to_api_obj_claude_sdk(json_str: str) -> Any:
    """
    Reconstruct output object from JSON string.

    For SDK, outputs are simple dicts so we just parse JSON.
    """
    parsed = json.loads(json_str)
    # Return the raw object if it exists, otherwise the whole thing
    return parsed.get("raw", parsed)


def json_str_to_original_inp_dict_claude_sdk(json_str: str, input_dict: dict) -> dict:
    """
    Reconstruct input dict from edited JSON string.

    Allows users to edit tool inputs in the UI (though editing is limited
    since we can't replay the subprocess).
    """
    parsed = json.loads(json_str)
    # Return the raw object if it exists, otherwise the whole thing
    return parsed.get("raw", parsed)
