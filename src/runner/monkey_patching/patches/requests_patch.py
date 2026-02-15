from functools import wraps
from ao.runner.monkey_patching.patching_utils import get_input_dict, send_graph_node_and_edges
from ao.runner.string_matching import find_source_nodes, store_output_strings
from ao.runner.context_manager import get_session_id
from ao.server.database_manager import DB
from ao.common.logger import logger
from ao.runner.monkey_patching.patching_utils import is_whitelisted_endpoint


def requests_patch():
    try:
        from requests import Session
    except ImportError:
        logger.info("requests not installed, skipping requests patches")
        return

    def create_patched_init(original_init):

        @wraps(original_init)
        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            patch_requests_send(self, type(self))

        return patched_init

    Session.__init__ = create_patched_init(Session.__init__)


def patch_requests_send(bound_obj, bound_cls):
    original_function = bound_obj.send

    @wraps(original_function)
    def patched_function(self, *args, **kwargs):

        api_type = "requests.Session.send"

        input_dict = get_input_dict(original_function, *args, **kwargs)

        request = input_dict["request"]
        url = str(request.url)
        path = request.path_url
        if not is_whitelisted_endpoint(url, path):
            return original_function(*args, **kwargs)

        # Content-based edge detection BEFORE get_in_out (uses original input)
        session_id = get_session_id()
        source_node_ids = find_source_nodes(session_id, input_dict, api_type)

        # Get result from cache or call LLM
        cache_output = DB.get_in_out(input_dict, api_type)
        if cache_output.output is None:
            result = original_function(**cache_output.input_dict)  # Call LLM
            DB.cache_output(cache_result=cache_output, output_obj=result, api_type=api_type)

        # Store output strings for future matching
        store_output_strings(
            cache_output.session_id, cache_output.node_id, cache_output.output, api_type
        )

        # Send graph node to server
        send_graph_node_and_edges(
            node_id=cache_output.node_id,
            input_dict=cache_output.input_dict,
            output_obj=cache_output.output,
            source_node_ids=source_node_ids,
            api_type=api_type,
            stack_trace=cache_output.stack_trace,
        )

        return cache_output.output

    bound_obj.send = patched_function.__get__(bound_obj, bound_cls)
