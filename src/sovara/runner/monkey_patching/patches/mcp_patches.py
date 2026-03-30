from functools import wraps
from sovara.runner.monkey_patching.patching_utils import get_input_dict, send_graph_node_and_edges
from sovara.runner.string_matching import find_source_nodes, store_output_strings
from sovara.runner.context_manager import get_run_id
from sovara.server.database_manager import DB
from sovara.common.logger import logger


def mcp_patch():
    try:
        from mcp.client.session import ClientSession
    except ImportError:
        logger.info("MCP not installed, skipping MCP patches")
        return

    def create_patched_init(original_init):

        @wraps(original_init)
        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            patch_mcp_send_request(self, type(self))

        return patched_init

    ClientSession.__init__ = create_patched_init(ClientSession.__init__)


def patch_mcp_send_request(bound_obj, bound_cls):
    original_function = bound_obj.send_request

    @wraps(original_function)
    async def patched_function(self, *args, **kwargs):
        api_type = "MCP.ClientSession.send_request"

        input_dict = get_input_dict(original_function, *args, **kwargs)

        # Check if this is a tools/call request
        request = input_dict.get("request")
        method = getattr(getattr(request, "root", None), "method", None) if request else None
        if method != "tools/call":
            return await original_function(*args, **kwargs)

        # Content-based edge detection BEFORE get_in_out (uses original input)
        run_id = get_run_id()
        source_node_ids = find_source_nodes(run_id, input_dict, api_type)

        # Get result from cache or call tool
        cache_output = DB.get_in_out(input_dict, api_type)
        if cache_output.output is None:
            result = await original_function(**cache_output.input_dict)  # Call tool
            DB.cache_output(cache_result=cache_output, output_obj=result, api_type=api_type)
        else:
            cache_output.output = input_dict["result_type"].model_validate(cache_output.output)

        # Store output strings for future matching
        store_output_strings(
            cache_output.run_id, cache_output.node_uuid, cache_output.output, api_type
        )

        # Send graph node to server
        send_graph_node_and_edges(
            node_id=cache_output.node_uuid,
            input_dict=cache_output.input_dict,
            output_obj=cache_output.output,
            source_node_ids=source_node_ids,
            api_type=api_type,
            stack_trace=cache_output.stack_trace,
            prior_count=None,
        )

        return cache_output.output

    bound_obj.send_request = patched_function.__get__(bound_obj, bound_cls)
