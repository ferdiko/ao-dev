import json
from typing import Any, Dict


def json_str_to_original_inp_dict_httpx(json_str: str, input_dict: dict) -> dict:
    import httpx

    # For httpx, modify both _content and stream
    # The stream is what actually gets sent over the wire
    input_dict_overwrite = json.loads(json_str)
    url = input_dict_overwrite["url"]
    body = input_dict_overwrite["body"]

    if body == "":
        new_content = b""
    else:
        new_content = json.dumps(body, sort_keys=True).encode("utf-8")

    input_dict["request"]._content = new_content
    input_dict["request"].stream = httpx.ByteStream(new_content)

    # Update URL
    input_dict["request"].url = httpx.URL(url)

    # Also update content-length header if present
    if "content-length" in input_dict["request"].headers:
        input_dict["request"].headers["content-length"] = str(len(new_content))

    return input_dict


def func_kwargs_to_json_str_httpx(input_dict: Dict[str, Any]):
    # For httpx, extract content from request object
    # Note: Request.content property always returns bytes (materializes stream if needed)
    content = input_dict["request"].content
    if content:
        body = content.decode("utf-8")
        try:
            # Try to parse as JSON
            body_json = json.loads(body)
        except json.JSONDecodeError:
            # Not JSON, store as raw string
            body_json = body
    else:
        body_json = ""

    url = str(input_dict["request"].url)
    json_str = json.dumps({
        "url": url,
        "body": body_json,
    }, sort_keys=True)

    return json_str, []


def api_obj_to_json_str_httpx(obj: Any) -> str:
    import dill
    import base64
    from httpx import Response

    obj: Response

    out_dict = {}
    encoding = obj.encoding if hasattr(obj, "encoding") else "utf-8"
    out_bytes = dill.dumps(obj)
    out_dict["_obj_str"] = base64.b64encode(out_bytes).decode(encoding)
    out_dict["_encoding"] = encoding
    decoded_content = obj.content.decode(encoding)
    try:
        out_dict["content"] = json.loads(decoded_content)
    except json.JSONDecodeError:
        out_dict["content"] = decoded_content

    return json.dumps(out_dict, sort_keys=True)


def json_str_to_api_obj_httpx(new_output_text: str) -> None:
    import dill
    import base64
    from httpx._decoders import TextDecoder

    out_dict = json.loads(new_output_text)
    encoding = out_dict["_encoding"] if "_encoding" in out_dict else "utf-8"
    obj = dill.loads(base64.b64decode(out_dict["_obj_str"].encode(encoding)))

    # For httpx.Response, update the content and text using the TextDecoder
    if isinstance(out_dict["content"], str):
        obj._content = out_dict["content"].encode(encoding)
    elif isinstance(out_dict["content"], dict):
        obj._content = json.dumps(out_dict["content"]).encode(encoding)
    else:
        raise Exception("out_dict['content'] is not dict or str after json.loads")

    decoder = TextDecoder(encoding=encoding)
    obj._text = "".join([decoder.decode(obj._content), decoder.flush()])
    return obj
