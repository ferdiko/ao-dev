import json
from typing import Any, Dict, List, Tuple
from sovara.common.logger import logger


def func_kwargs_to_json_str_mcp(
    input_dict: Dict[str, Any],
) -> Tuple[str, List[str]]:
    return (
        json.dumps(input_dict["request"].model_dump(by_alias=True, mode="json", exclude_none=True)),
        [],
    )


def api_obj_to_json_str_mcp(obj: Any) -> str:
    import mcp.types as mcp_types

    json_dict = obj.model_dump(by_alias=True, mode="json", exclude_none=True)
    # We use this to identify what type of class this was for json -> output object
    possible_matching_types = [k for k, v in vars(mcp_types).items() if v == obj.__class__]
    if len(possible_matching_types) == 1:
        json_dict["_type"] = possible_matching_types[0]
    return json.dumps(json_dict)


def json_str_to_api_obj_mcp(new_output_text: str) -> dict:
    import mcp.types as mcp_types

    json_dict = json.loads(new_output_text)
    _type = json_dict.pop("_type", None)
    if not _type:
        logger.error(f"[APIParser-MCP] no _type in json string from DB")
        return json_dict

    vars_types = vars(mcp_types)
    if not _type in vars_types:
        return json_dict

    obj = vars_types[_type].model_validate(json_dict)
    return obj


def json_str_to_original_inp_dict_mcp(json_str: str, input_dict: dict) -> dict:
    input_dict["request"] = input_dict["request"].model_validate(json.loads(json_str))
    return input_dict
