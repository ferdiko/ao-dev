from functools import wraps
from sovara.runner.monkey_patching.patching_utils import (
    get_input_dict,
    send_graph_node_and_edges,
)
from sovara.runner.string_matching import find_source_nodes, store_output_strings
from sovara.runner.context_manager import get_run_id
from sovara.runner.priors import persist_prior_metadata
from sovara.server.database_manager import DB
from sovara.common.logger import logger
from sovara.runner.monkey_patching.patching_utils import is_whitelisted_endpoint


def httpx_patch():
    try:
        from httpx import Client, AsyncClient
    except ImportError:
        logger.info("httpx not installed, skipping httpx patches")
        return

    def create_patched_init(original_init):

        @wraps(original_init)
        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            patch_httpx_send(self, type(self))

        return patched_init

    def async_create_patched_init(original_init):

        @wraps(original_init)
        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            patch_async_httpx_send(self, type(self))

        return patched_init

    Client.__init__ = create_patched_init(Client.__init__)
    AsyncClient.__init__ = async_create_patched_init(AsyncClient.__init__)


def patch_httpx_send(bound_obj, bound_cls):
    original_function = bound_obj.send

    @wraps(original_function)
    def patched_function(self, *args, **kwargs):

        api_type = "httpx.Client.send"

        input_dict = get_input_dict(original_function, *args, **kwargs)

        request = input_dict.get("request")
        if request is None:
            return original_function(*args, **kwargs)
        url = str(request.url)
        path = request.url.path
        if not is_whitelisted_endpoint(url, path):
            return original_function(*args, **kwargs)

        source_node_ids = find_source_nodes(get_run_id(), input_dict, api_type)

        # Get result from cache or call LLM (stack_trace captured inside get_in_out)
        cache_output = DB.get_in_out(input_dict, api_type, prepare_runtime_priors=True)
        prior_result = cache_output.prior_result
        if cache_output.output is None:
            result = original_function(**cache_output.input_dict)  # Call LLM
            DB.cache_output(cache_result=cache_output, output_obj=result, api_type=api_type)
        if prior_result is not None:
            persist_prior_metadata(cache_output.run_id, cache_output.node_uuid, prior_result.metadata)

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
            prior_count=len(prior_result.metadata.newly_applied_priors) if prior_result is not None else None,
        )

        return cache_output.output

    bound_obj.send = patched_function.__get__(bound_obj, bound_cls)


def patch_async_httpx_send(bound_obj, bound_cls):
    original_function = bound_obj.send

    @wraps(original_function)
    async def patched_function(self, *args, **kwargs):

        api_type = "httpx.AsyncClient.send"

        input_dict = get_input_dict(original_function, *args, **kwargs)

        request = input_dict.get("request")
        if request is None:
            return await original_function(*args, **kwargs)
        url = str(request.url)
        path = request.url.path
        if not is_whitelisted_endpoint(url, path):
            return await original_function(*args, **kwargs)

        source_node_ids = find_source_nodes(get_run_id(), input_dict, api_type)

        # Get result from cache or call LLM (stack_trace captured inside get_in_out)
        cache_output = DB.get_in_out(input_dict, api_type, prepare_runtime_priors=True)
        prior_result = cache_output.prior_result
        if cache_output.output is None:
            result = await original_function(**cache_output.input_dict)  # Call LLM
            DB.cache_output(cache_result=cache_output, output_obj=result, api_type=api_type)
        if prior_result is not None:
            persist_prior_metadata(cache_output.run_id, cache_output.node_uuid, prior_result.metadata)

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
            prior_count=len(prior_result.metadata.newly_applied_priors) if prior_result is not None else None,
        )

        return cache_output.output

    bound_obj.send = patched_function.__get__(bound_obj, bound_cls)
