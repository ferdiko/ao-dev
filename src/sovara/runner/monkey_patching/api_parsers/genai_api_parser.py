import json
import base64
from typing import Any, Dict


def json_str_to_original_inp_dict_genai(json_str: str, input_dict: dict) -> dict:
    """
    Reconstruct the input dictionary from the JSON string.
    For genai, we update the request_dict with the new values.
    """
    parsed = json.loads(json_str)
    input_dict["request_dict"] = parsed
    return input_dict


def func_kwargs_to_json_str_genai(input_dict: Dict[str, Any]):
    """
    Convert function kwargs to JSON string for genai BaseApiClient.async_request.
    The input_dict contains: http_method, path, request_dict, http_options
    We primarily care about the request_dict which contains the LLM request payload.
    """
    # The request_dict contains the actual LLM request payload
    request_dict = input_dict.get("request_dict", {})
    json_str = json.dumps(request_dict)
    return json_str, []


def api_obj_to_json_str_genai(obj: Any) -> str:
    """
    Convert the HttpResponse object to a JSON string.
    HttpResponse has headers (dict) and body (str - JSON formatted).
    """
    import dill

    out_dict = {}

    # Serialize the full object using dill for reconstruction
    out_bytes = dill.dumps(obj)
    out_dict["_obj_str"] = base64.b64encode(out_bytes).decode("utf-8")

    # Extract the body content for display (it's already JSON string)
    if hasattr(obj, "body") and obj.body:
        try:
            out_dict["content"] = json.loads(obj.body)
        except (json.JSONDecodeError, TypeError):
            out_dict["content"] = obj.body
    else:
        out_dict["content"] = {}

    return json.dumps(out_dict)


def json_str_to_api_obj_genai(new_output_text: str) -> Any:
    """
    Reconstruct the HttpResponse object from the JSON string.
    """
    import dill

    out_dict = json.loads(new_output_text)

    # Reconstruct the object from dill bytes
    obj = dill.loads(base64.b64decode(out_dict["_obj_str"].encode("utf-8")))

    # Update the body with the potentially edited content
    if "content" in out_dict:
        obj.body = json.dumps(out_dict["content"])

    return obj


