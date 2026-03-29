from functools import wraps

from sovara.common.logger import logger
from sovara.runner.context_manager import get_run_id
from sovara.runner.monkey_patching.patching_utils import (
    get_input_dict,
    send_graph_node_and_edges,
)
from sovara.runner.string_matching import find_source_nodes, store_output_strings
from sovara.server.database_manager import DB


def botocore_patch():
    try:
        from botocore.client import BaseClient
    except ImportError:
        logger.info("botocore not installed, skipping botocore patches")
        return

    original_function = BaseClient._make_api_call

    @wraps(original_function)
    def patched_function(self, *args, **kwargs):
        api_type = "botocore.BaseClient._make_api_call"

        input_dict = get_input_dict(original_function, self, *args, **kwargs)
        input_dict["service_name"] = self.meta.service_model.service_name

        operation_name = input_dict["operation_name"]
        if input_dict["service_name"] != "bedrock-runtime" or operation_name != "Converse":
            return original_function(self, *args, **kwargs)

        run_id = get_run_id()
        source_node_ids = find_source_nodes(run_id, input_dict, api_type)

        cache_output = DB.get_in_out(input_dict, api_type)
        if cache_output.output is None:
            input_dict_for_call = dict(cache_output.input_dict)
            input_dict_for_call.pop("service_name", None)
            result = original_function(self, **input_dict_for_call)
            DB.cache_output(cache_result=cache_output, output_obj=result, api_type=api_type)

        store_output_strings(
            cache_output.run_id, cache_output.node_uuid, cache_output.output, api_type
        )

        send_graph_node_and_edges(
            node_id=cache_output.node_uuid,
            input_dict=cache_output.input_dict,
            output_obj=cache_output.output,
            source_node_ids=source_node_ids,
            api_type=api_type,
            stack_trace=cache_output.stack_trace,
        )

        return cache_output.output

    BaseClient._make_api_call = patched_function
