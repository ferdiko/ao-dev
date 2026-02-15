import json
import re
from typing import Any, Dict, List, Tuple
from flatten_json import flatten, unflatten_list
from flatten_dict import unflatten, flatten as flatten_keep_list
from ao.runner.monkey_patching.api_parsers.mcp_api_parser import (
    func_kwargs_to_json_str_mcp,
    api_obj_to_json_str_mcp,
    json_str_to_api_obj_mcp,
    json_str_to_original_inp_dict_mcp,
)
from ao.runner.monkey_patching.api_parsers.httpx_api_parser import (
    func_kwargs_to_json_str_httpx,
    api_obj_to_json_str_httpx,
    json_str_to_api_obj_httpx,
    json_str_to_original_inp_dict_httpx,
)
from ao.runner.monkey_patching.api_parsers.requests_api_parser import (
    func_kwargs_to_json_str_requests,
    api_obj_to_json_str_requests,
    json_str_to_api_obj_requests,
    json_str_to_original_inp_dict_requests,
)
from ao.runner.monkey_patching.api_parsers.genai_api_parser import (
    func_kwargs_to_json_str_genai,
    api_obj_to_json_str_genai,
    json_str_to_api_obj_genai,
    json_str_to_original_inp_dict_genai,
)
from ao.runner.monkey_patching.api_parsers.claude_sdk_api_parser import (
    func_kwargs_to_json_str_claude_sdk,
    api_obj_to_json_str_claude_sdk,
    json_str_to_api_obj_claude_sdk,
    json_str_to_original_inp_dict_claude_sdk,
)
from ao.common.constants import EDIT_IO_EXCLUDE_PATTERNS


def flatten_to_show(inp):
    """
    Does this transformation:
    {"a": [{"b": {"c": 1}}], "d": 2} -> {"a": ["b.c": 1], "a.d": 2}
    This is nice to visualize since lists can be expanded (default)/collapsed
    but inside the lists, dicts are still flattened.
    """
    if isinstance(inp, dict):
        flattened = flatten_keep_list(inp, reducer="dot")
        flattened_lists = {}
        for key, value in flattened.items():
            if isinstance(value, list):
                flattened_lists[key] = [flatten_to_show(el) for el in value]
        for key, value in flattened_lists.items():
            flattened[key] = value
    else:
        flattened = inp
    return flattened


def unflatten_to_show(inp):
    """
    Reverts flatten_to_show.
    """
    if isinstance(inp, dict):
        unflattened_dict = unflatten(inp, splitter="dot")
        unflattened_lists = {}
        for key, value in unflattened_dict.items():
            if isinstance(value, list):
                unflattened_lists[key] = [unflatten_to_show(el) for el in value]

        for key, value in unflattened_lists.items():
            unflattened_dict[key] = value
    else:
        unflattened_dict = inp
    return unflattened_dict


def should_exclude_key(key: str) -> bool:
    """Check if a flattened key should be excluded based on regex patterns."""
    for pattern in EDIT_IO_EXCLUDE_PATTERNS:
        if re.match(pattern, key):
            return True
    return False


def filter_dict(input_dict: dict) -> dict:
    """Filter a dictionary by excluding keys matching exclude patterns."""
    flattened = flatten(input_dict, ".")
    filtered = {
        k: v for k, v in flattened.items() if not should_exclude_key(k) and not (v == [] or v == {})
    }
    unflattened = unflatten_list(filtered, ".")
    flattened_list_preserved = flatten_to_show(unflattened)
    return flattened_list_preserved


def merge_filtered_into_raw(raw_dict: dict, to_show_dict: dict) -> dict:
    """
    Merge values from to_show back into raw_dict.
    This updates the values in raw that exist in to_show while preserving structure and types.

    Important: Preserves numeric types (float vs int) from raw_dict to avoid API validation errors.
    For example, if raw has temperature: 0.0, we keep it as float even if JSON parsing made it 0.
    """
    # flatten the raw dict. the to-show is already flattened
    flattened_raw = flatten(raw_dict, ".")
    flattened_to_show = flatten(unflatten_to_show(to_show_dict), ".")

    # Update raw values with to_show values, preserving types from raw
    for key, value in flattened_to_show.items():
        if key in flattened_raw:
            flattened_raw[key] = value

    return unflatten_list(flattened_raw, ".")


def func_kwargs_to_json_str(input_dict: Dict[str, Any], api_type: str) -> Tuple[str, List[str]]:
    """
    Convert function kwargs to JSON string with filtered display version.

    Args:
        input_dict: Input dictionary containing function arguments
        api_type: The API type identifier

    Returns:
        Tuple of (JSON string with raw and to_show, list of additional metadata)
    """
    # Get the complete JSON string from the appropriate parser
    if api_type == "requests.Session.send":
        complete_json_str, metadata = func_kwargs_to_json_str_requests(input_dict)
    elif api_type in ["httpx.Client.send", "httpx.AsyncClient.send"]:
        complete_json_str, metadata = func_kwargs_to_json_str_httpx(input_dict)
    elif api_type == "MCP.ClientSession.send_request":
        complete_json_str, metadata = func_kwargs_to_json_str_mcp(input_dict)
    elif api_type == "genai.BaseApiClient.async_request":
        complete_json_str, metadata = func_kwargs_to_json_str_genai(input_dict)
    elif api_type == "claude_agent_sdk.parse_message":
        complete_json_str, metadata = func_kwargs_to_json_str_claude_sdk(input_dict)
    else:
        raise ValueError(f"Unknown API type {api_type}")

    # Parse the JSON string to get the raw dict
    raw_dict = json.loads(complete_json_str)

    # Filter the dict to create the display version
    to_show_dict = filter_dict(raw_dict)

    # Construct the wrapped format
    complete_dict = {"raw": raw_dict, "to_show": to_show_dict}

    # Return the wrapped JSON string
    return json.dumps(complete_dict), metadata


def json_str_to_original_inp_dict(json_str: str, input_dict: dict, api_type: str) -> dict:
    """
    Unpack the wrapped format and merge filtered values back into raw.

    Args:
        json_str: JSON string in format {"raw": {...}, "to_show": {...}}
        input_dict: Original input dictionary
        api_type: The API type identifier

    Returns:
        Updated input_dict with merged values
    """
    # Parse the wrapped format
    complete_dict = json.loads(json_str)

    # Extract raw and to_show
    raw_dict = complete_dict["raw"]
    to_show_dict = complete_dict["to_show"]

    # Merge to_show values back into raw
    merged_dict = merge_filtered_into_raw(raw_dict, to_show_dict)

    # Convert back to JSON string
    merged_json_str = json.dumps(merged_dict)

    # Feed to the appropriate parser
    if api_type == "requests.Session.send":
        return json_str_to_original_inp_dict_requests(merged_json_str, input_dict)
    elif api_type in ["httpx.Client.send", "httpx.AsyncClient.send"]:
        return json_str_to_original_inp_dict_httpx(merged_json_str, input_dict)
    elif api_type == "MCP.ClientSession.send_request":
        return json_str_to_original_inp_dict_mcp(merged_json_str, input_dict)
    elif api_type == "genai.BaseApiClient.async_request":
        return json_str_to_original_inp_dict_genai(merged_json_str, input_dict)
    elif api_type == "claude_agent_sdk.parse_message":
        return json_str_to_original_inp_dict_claude_sdk(merged_json_str, input_dict)
    else:
        return merged_dict


def api_obj_to_json_str(response_obj: Any, api_type: str) -> str:
    """
    Convert API response object to JSON string with filtered display version.

    Args:
        response_obj: The response object from the API call
        api_type: The API type identifier

    Returns:
        JSON string in format {"content": {...}, "to_show": {...}, others}
    """
    # Get the complete JSON string from the appropriate parser
    if api_type == "requests.Session.send":
        complete_json_str = api_obj_to_json_str_requests(response_obj)
    elif api_type in ["httpx.Client.send", "httpx.AsyncClient.send"]:
        complete_json_str = api_obj_to_json_str_httpx(response_obj)
    elif api_type == "MCP.ClientSession.send_request":
        complete_json_str = api_obj_to_json_str_mcp(response_obj)
    elif api_type == "genai.BaseApiClient.async_request":
        complete_json_str = api_obj_to_json_str_genai(response_obj)
    elif api_type == "claude_agent_sdk.parse_message":
        complete_json_str = api_obj_to_json_str_claude_sdk(response_obj)
    else:
        raise ValueError(f"Unknown API type {api_type}")

    # Parse the JSON string to get the raw dict
    raw_dict = json.loads(complete_json_str)
    # Filter the content dict
    to_show_dict = filter_dict(raw_dict)
    # Create to_show with filtered content
    final_dict = {"raw": raw_dict, "to_show": to_show_dict}
    # Return the wrapped JSON string

    # json_str_to_api_obj(json.dumps(final_dict), api_type)

    return json.dumps(final_dict)


def json_str_to_api_obj(new_output_text: str, api_type: str) -> Any:
    """
    Convert JSON string back to API object, merging filtered values.

    Args:
        new_output_text: JSON string in format {"content": {...}, "to_show": {...}, others}
        api_type: The API type identifier

    Returns:
        Reconstructed API response object
    """
    # Parse the wrapped format
    complete_dict = json.loads(new_output_text)
    raw_dict = complete_dict["raw"]
    to_show_dict = complete_dict["to_show"]
    merged_dict = merge_filtered_into_raw(raw_dict, to_show_dict)
    merged_json_str = json.dumps(merged_dict)

    # Feed to the appropriate parser
    if api_type == "requests.Session.send":
        return json_str_to_api_obj_requests(merged_json_str)
    elif api_type in ["httpx.Client.send", "httpx.AsyncClient.send"]:
        return json_str_to_api_obj_httpx(merged_json_str)
    elif api_type == "MCP.ClientSession.send_request":
        return json_str_to_api_obj_mcp(merged_json_str)
    elif api_type == "genai.BaseApiClient.async_request":
        return json_str_to_api_obj_genai(merged_json_str)
    elif api_type == "claude_agent_sdk.parse_message":
        return json_str_to_api_obj_claude_sdk(merged_json_str)
    else:
        raise ValueError(f"Unknown API type {api_type}")


def api_obj_to_response_ok(response_obj: Any, api_type: str) -> bool:
    if api_type == "requests.Session.send":
        return response_obj.ok
    elif api_type in ["httpx.Client.send", "httpx.AsyncClient.send"]:
        return response_obj.is_success
    elif api_type == "MCP.ClientSession.send_request":
        # MCP tool responses should always be cached for replay, even if isError=True.
        # Unlike HTTP errors (which may be transient), MCP tool errors are deterministic
        # responses that should be replayed consistently.
        return True
    else:
        return True
