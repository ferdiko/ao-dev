import io
import re
import sys
from functools import wraps
from urllib.parse import urlparse

from sovara.common.logger import logger
from sovara.runner.context_manager import get_run_id
from sovara.runner.monkey_patching.patching_utils import (
    get_input_dict,
    is_whitelisted_endpoint,
    send_graph_node_and_edges,
)
from sovara.runner.string_matching import find_source_nodes, store_output_strings
from sovara.server.database_manager import DB


API_TYPE = "urllib3.HTTPConnectionPool.urlopen"
INTERNAL_FIELDS = {"full_url", "pool_scheme", "pool_host", "pool_port"}


def _build_full_url(pool, url: str) -> str:
    if re.match(r"^https?://", url):
        return url

    scheme = getattr(pool, "scheme", "http")
    host = getattr(pool, "host", "")
    port = getattr(pool, "port", None)

    default_port = 443 if scheme == "https" else 80
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    path = url if url.startswith("/") else f"/{url}"
    return f"{scheme}://{netloc}{path}"


def _is_botocore_stack() -> bool:
    frame = sys._getframe()
    while frame is not None:
        filename = frame.f_code.co_filename.replace("\\", "/")
        if "/botocore/" in filename:
            return True
        frame = frame.f_back
    return False


def _should_intercept_bedrock_request(input_dict: dict) -> bool:
    full_url = input_dict["full_url"]
    path = urlparse(full_url).path
    return _is_botocore_stack() and is_whitelisted_endpoint(full_url, path)


def _call_original(original_function, pool, input_dict: dict):
    original_kwargs = {
        key: value for key, value in input_dict.items()
        if key not in INTERNAL_FIELDS
    }
    return original_function(pool, **original_kwargs)


def _make_replayable_response(response):
    from urllib3.response import HTTPResponse

    body_bytes = response.read(cache_content=True, decode_content=False)
    if hasattr(response, "release_conn"):
        response.release_conn()

    headers = dict(response.headers.items())
    headers.setdefault("content-length", str(len(body_bytes)))

    return HTTPResponse(
        body=io.BytesIO(body_bytes),
        headers=headers,
        status=response.status,
        version=response.version,
        version_string=response.version_string,
        reason=response.reason,
        preload_content=False,
        decode_content=False,
        request_url=getattr(response, "_request_url", None),
    )


def urllib3_patch():
    try:
        from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
    except ImportError:
        logger.info("urllib3 not installed, skipping urllib3 patches")
        return

    patch_urllib3_urlopen(HTTPConnectionPool)
    patch_urllib3_urlopen(HTTPSConnectionPool)


def patch_urllib3_urlopen(bound_cls):
    original_function = bound_cls.urlopen

    @wraps(original_function)
    def patched_function(self, *args, **kwargs):
        input_dict = get_input_dict(original_function, self, *args, **kwargs)
        input_dict["pool_scheme"] = getattr(self, "scheme", "http")
        input_dict["pool_host"] = getattr(self, "host", "")
        input_dict["pool_port"] = getattr(self, "port", None)
        input_dict["full_url"] = _build_full_url(self, input_dict["url"])

        if not _should_intercept_bedrock_request(input_dict):
            return original_function(self, *args, **kwargs)

        run_id = get_run_id()
        source_node_ids = find_source_nodes(run_id, input_dict, API_TYPE)

        cache_output = DB.get_in_out(input_dict, API_TYPE)
        if cache_output.output is None:
            result = _call_original(original_function, self, cache_output.input_dict)
            result = _make_replayable_response(result)
            DB.cache_output(cache_result=cache_output, output_obj=result, api_type=API_TYPE)

        store_output_strings(
            cache_output.run_id, cache_output.node_uuid, cache_output.output, API_TYPE
        )

        send_graph_node_and_edges(
            node_id=cache_output.node_uuid,
            input_dict=cache_output.input_dict,
            output_obj=cache_output.output,
            source_node_ids=source_node_ids,
            api_type=API_TYPE,
            stack_trace=cache_output.stack_trace,
        )

        return cache_output.output

    bound_cls.urlopen = patched_function
