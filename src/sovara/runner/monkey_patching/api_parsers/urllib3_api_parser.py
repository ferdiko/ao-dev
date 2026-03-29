import io
import json
from typing import Any, Dict


def _serialize_body(body: Any) -> tuple[Any, bool]:
    if body in (None, b"", ""):
        return "", isinstance(body, bytes)

    if isinstance(body, bytes):
        decoded = body.decode("utf-8")
        try:
            return json.loads(decoded), True
        except json.JSONDecodeError:
            return decoded, True

    if isinstance(body, str):
        try:
            return json.loads(body), False
        except json.JSONDecodeError:
            return body, False

    return str(body), False


def _restore_body(body: Any, body_encoded: bool) -> Any:
    if body == "":
        return None

    if isinstance(body, (dict, list)):
        restored = json.dumps(body, sort_keys=True)
    else:
        restored = body

    if body_encoded and isinstance(restored, str):
        return restored.encode("utf-8")

    return restored


def json_str_to_original_inp_dict_urllib3(json_str: str, input_dict: dict) -> dict:
    input_dict_overwrite = json.loads(json_str)
    input_dict["method"] = input_dict_overwrite["method"]
    input_dict["url"] = input_dict_overwrite["path"]
    input_dict["body"] = _restore_body(
        input_dict_overwrite["body"],
        input_dict_overwrite["_body_encoded"],
    )
    input_dict["full_url"] = input_dict_overwrite["url"]
    input_dict["pool_scheme"] = input_dict_overwrite["pool_scheme"]
    input_dict["pool_host"] = input_dict_overwrite["pool_host"]
    input_dict["pool_port"] = input_dict_overwrite["pool_port"]
    return input_dict


def func_kwargs_to_json_str_urllib3(input_dict: Dict[str, Any]):
    body, body_encoded = _serialize_body(input_dict.get("body"))
    json_str = json.dumps(
        {
            "method": input_dict["method"],
            "url": input_dict["full_url"],
            "path": input_dict["url"],
            "body": body,
            "_body_encoded": body_encoded,
            "pool_scheme": input_dict["pool_scheme"],
            "pool_host": input_dict["pool_host"],
            "pool_port": input_dict["pool_port"],
        },
        sort_keys=True,
    )
    return json_str, []


def _extract_body_bytes(obj: Any) -> bytes:
    body_bytes = obj.read(cache_content=True, decode_content=False)
    obj._body = body_bytes
    obj._fp = io.BytesIO(body_bytes)
    obj._fp_bytes_read = 0
    obj.length_remaining = len(body_bytes)
    return body_bytes


def api_obj_to_json_str_urllib3(obj: Any) -> str:
    from json import JSONDecodeError

    body_bytes = _extract_body_bytes(obj)

    try:
        content = json.loads(body_bytes.decode("utf-8")) if body_bytes else ""
    except (UnicodeDecodeError, JSONDecodeError):
        content = body_bytes.decode("utf-8") if body_bytes else ""

    out_dict = {
        "status": obj.status,
        "reason": obj.reason,
        "version": obj.version,
        "version_string": obj.version_string,
        "request_url": getattr(obj, "_request_url", None),
        "headers": dict(obj.headers.items()),
        "content": content,
    }
    return json.dumps(out_dict, sort_keys=True)


def json_str_to_api_obj_urllib3(new_output_text: str) -> Any:
    from urllib3.response import HTTPResponse

    out_dict = json.loads(new_output_text)
    if isinstance(out_dict["content"], str):
        body_bytes = out_dict["content"].encode("utf-8")
    elif isinstance(out_dict["content"], (dict, list)):
        body_bytes = json.dumps(out_dict["content"], separators=(",", ":")).encode("utf-8")
    else:
        raise Exception("out_dict['content'] is not dict, list, or str after json.loads")

    headers = dict(out_dict.get("headers", {}))
    headers.setdefault("content-length", str(len(body_bytes)))

    return HTTPResponse(
        body=io.BytesIO(body_bytes),
        headers=headers,
        status=out_dict["status"],
        version=out_dict.get("version", 0),
        version_string=out_dict.get("version_string", "HTTP/?"),
        reason=out_dict.get("reason"),
        preload_content=False,
        decode_content=False,
        request_url=out_dict.get("request_url"),
    )
