import json

from sovara.runner.monkey_patching.api_parser import (
    api_obj_to_json_str,
    func_kwargs_to_json_str,
    json_str_to_api_obj,
)
from sovara.runner.monkey_patching.patching_utils import get_node_label


API_TYPE = "botocore.BaseClient._make_api_call"


def _bedrock_input_dict(model_id: str = "amazon.nova-lite-v1:0") -> dict:
    return {
        "service_name": "bedrock-runtime",
        "operation_name": "Converse",
        "api_params": {
            "modelId": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": "Hello from Amazon Nova"}],
                }
            ],
            "inferenceConfig": {"temperature": 0, "maxTokens": 64},
        },
    }


def test_bedrock_model_ids_use_nova_display_aliases():
    label = get_node_label(_bedrock_input_dict(), API_TYPE)
    assert label == "Amazon Nova Lite"


def test_bedrock_api_parser_round_trips_dict_payloads():
    input_json, _ = func_kwargs_to_json_str(_bedrock_input_dict(), API_TYPE)
    input_payload = json.loads(input_json)
    assert input_payload["raw"]["api_params"]["modelId"] == "amazon.nova-lite-v1:0"

    output_obj = {
        "output": {
            "message": {
                "content": [{"text": "Nova says hello"}],
            }
        }
    }
    output_json = api_obj_to_json_str(output_obj, API_TYPE)

    assert json_str_to_api_obj(output_json, API_TYPE) == output_obj
