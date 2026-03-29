import json
from typing import Any, Dict


def json_str_to_original_inp_dict_botocore(json_str: str, input_dict: dict) -> dict:
    input_dict_overwrite = json.loads(json_str)
    input_dict["service_name"] = input_dict_overwrite["service_name"]
    input_dict["operation_name"] = input_dict_overwrite["operation_name"]
    input_dict["api_params"] = input_dict_overwrite["api_params"]
    return input_dict


def func_kwargs_to_json_str_botocore(input_dict: Dict[str, Any]):
    json_str = json.dumps(
        {
            "service_name": input_dict["service_name"],
            "operation_name": input_dict["operation_name"],
            "api_params": input_dict["api_params"],
        },
        sort_keys=True,
    )
    return json_str, []


def api_obj_to_json_str_botocore(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True)


def json_str_to_api_obj_botocore(new_output_text: str) -> Any:
    return json.loads(new_output_text)
