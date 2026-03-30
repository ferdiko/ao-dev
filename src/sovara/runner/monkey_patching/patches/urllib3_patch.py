import io
import re
import sys
from functools import wraps
from urllib.parse import quote, urlparse, urlsplit

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
PATCH_MARKER = "__sovara_urllib3_patched__"


def _normalize_relative_url(url: str) -> str:
    parsed = urlsplit(url)
    normalized_path = quote(parsed.path or "/", safe="/%")
    if parsed.query:
        return f"{normalized_path}?{parsed.query}"
    return normalized_path


def _build_full_url_from_parts(scheme: str, host: str, port: int | None, url: str) -> str:
    if re.match(r"^https?://", url):
        return url

    default_port = 443 if scheme == "https" else 80
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    path = _normalize_relative_url(url if url.startswith("/") else f"/{url}")
    return f"{scheme}://{netloc}{path}"


def _build_full_url(pool, url: str) -> str:
    return _build_full_url_from_parts(
        getattr(pool, "scheme", "http"),
        getattr(pool, "host", ""),
        getattr(pool, "port", None),
        url,
    )


def _extract_relative_url(full_url: str) -> str:
    parsed = urlsplit(full_url)
    return _normalize_relative_url(parsed.path + (f"?{parsed.query}" if parsed.query else ""))


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


def _copy_request_context(request_context: dict | None) -> dict:
    copied = dict(request_context or {})
    for key in ("retries", "signing"):
        if isinstance(copied.get(key), dict):
            copied[key] = dict(copied[key])
    return copied


def _copy_headers(headers) -> dict:
    if headers is None:
        return {}
    if hasattr(headers, "items"):
        return dict(headers.items())
    return dict(headers)


def _prepare_headers_for_resigning(headers: dict) -> dict:
    refreshed = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in {"authorization", "content-length", "x-amz-date", "x-amz-security-token"}:
            continue
        refreshed[key] = value
    return refreshed


def _find_botocore_request_signer():
    frame = sys._getframe()
    while frame is not None:
        filename = frame.f_code.co_filename.replace("\\", "/")
        if filename.endswith("/botocore/client.py") and frame.f_code.co_name == "_make_api_call":
            client = frame.f_locals.get("self")
            operation_name = frame.f_locals.get("operation_name")
            request_context = frame.f_locals.get("request_context")
            request_signer = getattr(client, "_request_signer", None)
            if request_signer is not None and operation_name and isinstance(request_context, dict):
                return request_signer, operation_name, request_context
        frame = frame.f_back
    return None, None, None


def _apply_botocore_signature(
    input_dict: dict,
    request_signer,
    operation_name: str,
    request_context: dict,
    aws_request_cls,
) -> dict:
    aws_request = aws_request_cls(
        method=input_dict["method"],
        url=input_dict["full_url"],
        headers=_prepare_headers_for_resigning(_copy_headers(input_dict.get("headers"))),
        data=input_dict.get("body"),
    )
    aws_request.context = _copy_request_context(request_context)
    request_signer.sign(operation_name, aws_request)
    prepared_request = aws_request.prepare()
    input_dict["method"] = prepared_request.method
    input_dict["full_url"] = prepared_request.url
    input_dict["url"] = _extract_relative_url(prepared_request.url)
    input_dict["body"] = prepared_request.body
    input_dict["headers"] = _copy_headers(prepared_request.headers)
    return input_dict


def _resign_botocore_request(input_dict: dict) -> dict:
    try:
        from botocore.awsrequest import AWSRequest
    except ImportError as exc:
        raise RuntimeError("botocore must be importable to re-sign Bedrock requests") from exc

    request_signer, operation_name, request_context = _find_botocore_request_signer()
    if request_signer is None:
        raise RuntimeError("Could not locate botocore request signer for urllib3 request replay")

    return _apply_botocore_signature(
        input_dict=input_dict,
        request_signer=request_signer,
        operation_name=operation_name,
        request_context=request_context,
        aws_request_cls=AWSRequest,
    )


def _prepare_replayed_request(input_dict: dict, original_request: dict) -> dict:
    url_changed = input_dict.get("url") != original_request.get("url")
    full_url_changed = input_dict.get("full_url") != original_request.get("full_url")
    request_changed = (
        input_dict.get("method") != original_request.get("method")
        or input_dict.get("body") != original_request.get("body")
        or url_changed
        or full_url_changed
    )
    if not request_changed:
        return input_dict

    if url_changed:
        input_dict["url"] = _normalize_relative_url(input_dict["url"])
        input_dict["full_url"] = _build_full_url_from_parts(
            input_dict["pool_scheme"],
            input_dict["pool_host"],
            input_dict["pool_port"],
            input_dict["url"],
        )
    else:
        input_dict["url"] = _extract_relative_url(input_dict["full_url"])
        input_dict["full_url"] = _build_full_url_from_parts(
            input_dict["pool_scheme"],
            input_dict["pool_host"],
            input_dict["pool_port"],
            input_dict["url"],
        )

    return _resign_botocore_request(input_dict)


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
    # HTTPSConnectionPool inherits urlopen from HTTPConnectionPool, so guard against
    # wrapping the same method twice when we patch both classes.
    if getattr(bound_cls.urlopen, PATCH_MARKER, False):
        return

    original_function = bound_cls.urlopen

    @wraps(original_function)
    def patched_function(self, *args, **kwargs):
        input_dict = get_input_dict(original_function, self, *args, **kwargs)
        input_dict["pool_scheme"] = getattr(self, "scheme", "http")
        input_dict["pool_host"] = getattr(self, "host", "")
        input_dict["pool_port"] = getattr(self, "port", None)
        input_dict["full_url"] = _build_full_url(self, input_dict["url"])
        original_request = {
            "method": input_dict.get("method"),
            "url": input_dict.get("url"),
            "full_url": input_dict.get("full_url"),
            "body": input_dict.get("body"),
        }

        if not _should_intercept_bedrock_request(input_dict):
            return original_function(self, *args, **kwargs)

        run_id = get_run_id()
        source_node_ids = find_source_nodes(run_id, input_dict, API_TYPE)

        cache_output = DB.get_in_out(input_dict, API_TYPE)
        if cache_output.output is None:
            _prepare_replayed_request(cache_output.input_dict, original_request)
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

    setattr(patched_function, PATCH_MARKER, True)
    bound_cls.urlopen = patched_function
