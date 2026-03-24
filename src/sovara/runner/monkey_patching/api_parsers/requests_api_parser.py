import json
from typing import Any, Dict


def json_str_to_original_inp_dict_requests(json_str: str, input_dict: dict) -> dict:
    # For requests, modify the request body
    input_dict_overwrite = json.loads(json_str)
    url = input_dict_overwrite["url"]
    body = input_dict_overwrite["body"]
    _body_encoded = input_dict_overwrite["_body_encoded"]

    if body == "":
       input_dict["request"].body = None
    else:
        body_json_str = json.dumps(body, sort_keys=True)
        if _body_encoded:
            body_json_str = body_json_str.encode("utf-8")
        input_dict["request"].body = body_json_str
        input_dict["request"].prepare_content_length(body_json_str)

    # change the url
    input_dict["request"].url = url

    return input_dict


def func_kwargs_to_json_str_requests(input_dict: Dict[str, Any]):
    # For requests, extract body from request object
    _body_encoded = False
    if input_dict["request"].body:
        body = input_dict["request"].body
        if isinstance(body, bytes):
            _body_encoded = True
            body = body.decode("utf-8")
        body_json = json.loads(body)
    else:
        body_json = ""
    
    url = str(input_dict["request"].url)
    json_str = json.dumps({
        "url": url,
        "body": body_json,
        "_body_encoded": _body_encoded
    }, sort_keys=True)

    return json_str, []


def api_obj_to_json_str_requests(obj: Any) -> str:
    import dill
    import base64
    from json import JSONDecodeError

    out_dict = {}
    encoding = obj.encoding if hasattr(obj, "encoding") else "utf-8"
    out_bytes = dill.dumps(obj)
    out_dict["_obj_str"] = base64.b64encode(out_bytes).decode(encoding)
    out_dict["_encoding"] = encoding
    decoded_content = obj.content.decode(encoding)
    try:
        out_dict["content"] = json.loads(decoded_content)
    except JSONDecodeError:
        out_dict["content"] = decoded_content    

    return json.dumps(out_dict, sort_keys=True)


def json_str_to_api_obj_requests(new_output_text: str) -> None:
    import dill
    import base64

    out_dict = json.loads(new_output_text)
    encoding = out_dict["_encoding"] if "_encoding" in out_dict else "utf-8"
    obj = dill.loads(base64.b64decode(out_dict["_obj_str"].encode(encoding)))

    # For requests.Response, update the content and text attributes
    if isinstance(out_dict["content"], str):
        obj._content = out_dict["content"].encode(encoding)
    elif isinstance(out_dict["content"], dict):
        obj._content = json.dumps(out_dict["content"]).encode(encoding)
    else:
        raise Exception("out_dict['content'] is not dict or str after json.loads")

    # requests.Response doesn't have a decoder like httpx, it computes _text on access
    # So we just need to clear the cached _text to force recomputation
    if hasattr(obj, "_content_consumed"):
        obj._content_consumed = False
    return obj
