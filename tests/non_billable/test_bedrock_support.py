import io
import json

import pytest
from urllib3.response import HTTPResponse

from sovara.runner.monkey_patching.api_parser import (
    api_obj_to_json_str,
    func_kwargs_to_json_str,
    json_str_to_api_obj,
)
from sovara.runner.monkey_patching.patches import urllib3_patch as urllib3_patch_module
from sovara.runner.monkey_patching.patches.urllib3_patch import (
    API_TYPE,
    _apply_botocore_signature,
    _build_full_url,
    _make_replayable_response,
    _prepare_replayed_request,
    patch_urllib3_urlopen,
)
from sovara.runner.monkey_patching.patching_utils import get_node_label
from sovara.server.database_manager import CacheOutput


def _bedrock_input_dict(model_id: str = "amazon.nova-lite-v1:0") -> dict:
    encoded_model_id = model_id.replace(":", "%3A")
    return {
        "method": "POST",
        "url": f"/model/{encoded_model_id}/converse",
        "full_url": (
            f"https://bedrock-runtime.us-east-1.amazonaws.com/model/{encoded_model_id}/converse"
        ),
        "body": json.dumps(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": "Hello from Amazon Nova"}],
                    }
                ],
                "inferenceConfig": {"temperature": 0, "maxTokens": 64},
            }
        ).encode("utf-8"),
        "headers": {"content-type": "application/json"},
        "pool_scheme": "https",
        "pool_host": "bedrock-runtime.us-east-1.amazonaws.com",
        "pool_port": 443,
    }


def _make_response(body_bytes: bytes | None = None) -> HTTPResponse:
    body_bytes = body_bytes or b'{"output":{"message":{"content":[{"text":"Nova says hello"}]}}}'
    return HTTPResponse(
        body=io.BytesIO(body_bytes),
        headers={
            "content-type": "application/json",
            "content-length": str(len(body_bytes)),
        },
        status=200,
        reason="OK",
        preload_content=False,
        decode_content=False,
        request_method="POST",
        request_url="https://bedrock-runtime.us-east-1.amazonaws.com/model/amazon.nova-lite-v1%3A0/converse",
    )


def test_build_full_url_uses_pool_host_for_relative_paths():
    class FakePool:
        scheme = "https"
        host = "bedrock-runtime.us-east-1.amazonaws.com"
        port = 443

    assert _build_full_url(FakePool(), "/model/amazon.nova-lite-v1:0/converse") == (
        "https://bedrock-runtime.us-east-1.amazonaws.com/model/amazon.nova-lite-v1%3A0/converse"
    )


def test_bedrock_model_ids_use_nova_display_aliases():
    label = get_node_label(_bedrock_input_dict(), API_TYPE)
    assert label == "Amazon Nova Lite"


def test_should_intercept_bedrock_request_requires_botocore_stack(monkeypatch):
    monkeypatch.setattr(urllib3_patch_module, "_is_botocore_stack", lambda: False)
    assert not urllib3_patch_module._should_intercept_bedrock_request(_bedrock_input_dict())

    monkeypatch.setattr(urllib3_patch_module, "_is_botocore_stack", lambda: True)
    assert urllib3_patch_module._should_intercept_bedrock_request(_bedrock_input_dict())


def test_urllib3_api_parser_round_trips_bedrock_request_and_response():
    input_json, _ = func_kwargs_to_json_str(_bedrock_input_dict(), API_TYPE)
    input_payload = json.loads(input_json)
    assert input_payload["raw"]["url"].endswith("/model/amazon.nova-lite-v1%3A0/converse")
    assert input_payload["raw"]["body"]["messages"][0]["content"][0]["text"] == "Hello from Amazon Nova"

    output_json = api_obj_to_json_str(_make_response(), API_TYPE)
    reconstructed = json_str_to_api_obj(output_json, API_TYPE)

    assert reconstructed.status == 200
    assert list(reconstructed.stream()) == [
        b'{"output":{"message":{"content":[{"text":"Nova says hello"}]}}}'
    ]


def test_make_replayable_response_returns_streamable_clone():
    replayable = _make_replayable_response(_make_response())
    assert list(replayable.stream()) == [
        b'{"output":{"message":{"content":[{"text":"Nova says hello"}]}}}'
    ]


def test_patch_urllib3_urlopen_falls_through_for_non_bedrock(monkeypatch):
    class FakePool:
        scheme = "https"
        host = "api.openai.com"
        port = 443

        def __init__(self):
            self.original_calls = 0

        def urlopen(self, method, url, body=None, headers=None, **kwargs):
            self.original_calls += 1
            return {"source": "original", "url": url}

    patch_urllib3_urlopen(FakePool)
    monkeypatch.setattr(urllib3_patch_module, "_should_intercept_bedrock_request", lambda _: False)

    pool = FakePool()
    response = pool.urlopen("POST", "/v1/responses", body=b"{}", headers={})

    assert response == {"source": "original", "url": "/v1/responses"}
    assert pool.original_calls == 1


def test_patch_urllib3_urlopen_is_idempotent_for_inherited_pools(monkeypatch):
    class BasePool:
        scheme = "https"
        host = "bedrock-runtime.us-east-1.amazonaws.com"
        port = 443

        def __init__(self):
            self.original_calls = 0

        def urlopen(self, method, url, body=None, headers=None, **kwargs):
            self.original_calls += 1
            return {"source": "original", "url": url}

    class ChildPool(BasePool):
        pass

    intercept_checks = {"count": 0}

    def fake_should_intercept(_):
        intercept_checks["count"] += 1
        return False

    patch_urllib3_urlopen(BasePool)
    patch_urllib3_urlopen(ChildPool)
    monkeypatch.setattr(urllib3_patch_module, "_should_intercept_bedrock_request", fake_should_intercept)

    pool = ChildPool()
    response = pool.urlopen("POST", "/model/amazon.nova-lite-v1:0/converse", body=b"{}", headers={})

    assert response == {"source": "original", "url": "/model/amazon.nova-lite-v1:0/converse"}
    assert pool.original_calls == 1
    assert intercept_checks["count"] == 1


def test_apply_botocore_signature_refreshes_stale_body_sensitive_headers():
    captured = {}

    class FakeSigner:
        def sign(self, operation_name, aws_request):
            captured["operation_name"] = operation_name
            captured["request_context"] = dict(aws_request.context)
            captured["headers_before_sign"] = dict(aws_request.headers.items())
            aws_request.headers["Authorization"] = "AWS4-HMAC-SHA256 fresh"
            aws_request.headers["X-Amz-Date"] = "20260329T121802Z"

    class FakePreparedRequest:
        def __init__(self, method, url, headers, body):
            self.method = method
            self.url = url
            self.headers = headers
            self.body = body

    class FakeAWSRequest:
        def __init__(self, method, url, headers, data):
            self.method = method
            self.url = url
            self.headers = headers
            self.data = data
            self.context = {}

        def prepare(self):
            headers = dict(self.headers.items())
            headers["Content-Length"] = str(len(self.data))
            return FakePreparedRequest(self.method, self.url, headers, self.data)

    input_dict = _bedrock_input_dict()
    input_dict["body"] = b'{"messages":[{"role":"user","content":[{"text":"Edited"}]}]}'
    input_dict["headers"] = {
        "Authorization": "stale-auth",
        "Content-Length": "999",
        "X-Amz-Date": "stale-date",
        "X-Amz-Security-Token": "stale-token",
        "User-Agent": "bedrock-test",
    }

    signed = _apply_botocore_signature(
        input_dict=input_dict,
        request_signer=FakeSigner(),
        operation_name="Converse",
        request_context={"client_region": "us-east-1", "timestamp": "stale"},
        aws_request_cls=FakeAWSRequest,
    )

    assert captured["operation_name"] == "Converse"
    assert captured["request_context"]["client_region"] == "us-east-1"
    assert "Authorization" not in captured["headers_before_sign"]
    assert "Content-Length" not in captured["headers_before_sign"]
    assert "X-Amz-Date" not in captured["headers_before_sign"]
    assert "X-Amz-Security-Token" not in captured["headers_before_sign"]
    assert captured["headers_before_sign"]["User-Agent"] == "bedrock-test"
    assert signed["headers"]["Authorization"] == "AWS4-HMAC-SHA256 fresh"
    assert signed["headers"]["Content-Length"] == str(len(input_dict["body"]))


def test_prepare_replayed_request_normalizes_bedrock_model_paths(monkeypatch):
    original_request = _bedrock_input_dict()
    replay_request = dict(original_request)
    replay_request["body"] = b'{"messages":[{"role":"user","content":[{"text":"Edited"}]}]}'
    replay_request["url"] = "/model/amazon.nova-lite-v1:0/converse"

    captured = {}

    def fake_resign(input_dict):
        captured["url"] = input_dict["url"]
        captured["full_url"] = input_dict["full_url"]
        input_dict["headers"] = {"Authorization": "fresh"}
        return input_dict

    monkeypatch.setattr(urllib3_patch_module, "_resign_botocore_request", fake_resign)

    result = _prepare_replayed_request(replay_request, original_request)

    assert captured["url"].endswith("/model/amazon.nova-lite-v1%3A0/converse")
    assert captured["full_url"].endswith("/model/amazon.nova-lite-v1%3A0/converse")
    assert result["headers"]["Authorization"] == "fresh"


def test_patch_urllib3_urlopen_intercepts_bedrock_and_uses_cache_flow(monkeypatch):
    class FakePool:
        scheme = "https"
        host = "bedrock-runtime.us-east-1.amazonaws.com"
        port = 443

        def __init__(self):
            self.original_calls = 0

        def urlopen(self, method, url, body=None, headers=None, **kwargs):
            self.original_calls += 1
            return _make_response()

    patch_urllib3_urlopen(FakePool)
    monkeypatch.setattr(urllib3_patch_module, "_should_intercept_bedrock_request", lambda _: True)
    monkeypatch.setattr(urllib3_patch_module, "get_run_id", lambda: "run-1")
    monkeypatch.setattr(urllib3_patch_module, "find_source_nodes", lambda *args, **kwargs: ["node-a"])

    captured = {"store_calls": 0, "graph_calls": 0}

    def fake_get_in_out(input_dict, api_type):
        captured["api_type"] = api_type
        captured["full_url"] = input_dict["full_url"]
        return CacheOutput(
            input_dict=input_dict,
            output=None,
            node_uuid="node-b",
            input_pickle=b"",
            input_hash="hash",
            run_id="run-1",
            stack_trace="stack",
        )

    def fake_cache_output(cache_result, output_obj, api_type, cache=True):
        cache_result.output = output_obj
        captured["cached_api_type"] = api_type

    monkeypatch.setattr(urllib3_patch_module.DB, "get_in_out", fake_get_in_out)
    monkeypatch.setattr(urllib3_patch_module.DB, "cache_output", fake_cache_output)
    monkeypatch.setattr(
        urllib3_patch_module,
        "store_output_strings",
        lambda *args, **kwargs: captured.__setitem__("store_calls", captured["store_calls"] + 1),
    )
    monkeypatch.setattr(
        urllib3_patch_module,
        "send_graph_node_and_edges",
        lambda *args, **kwargs: captured.__setitem__("graph_calls", captured["graph_calls"] + 1),
    )

    pool = FakePool()
    response = pool.urlopen(
        "POST",
        "/model/amazon.nova-lite-v1%3A0/converse",
        body=_bedrock_input_dict()["body"],
        headers={"content-type": "application/json"},
    )

    assert pool.original_calls == 1
    assert captured["api_type"] == API_TYPE
    assert captured["cached_api_type"] == API_TYPE
    assert captured["full_url"].endswith("/model/amazon.nova-lite-v1%3A0/converse")
    assert captured["store_calls"] == 1
    assert captured["graph_calls"] == 1
    assert list(response.stream()) == [
        b'{"output":{"message":{"content":[{"text":"Nova says hello"}]}}}'
    ]


def test_patch_urllib3_urlopen_replays_edited_requests_through_resigning(monkeypatch):
    class FakePool:
        scheme = "https"
        host = "bedrock-runtime.us-east-1.amazonaws.com"
        port = 443

        def __init__(self):
            self.original_calls = 0
            self.last_url = None
            self.last_headers = None

        def urlopen(self, method, url, body=None, headers=None, **kwargs):
            self.original_calls += 1
            self.last_url = url
            self.last_headers = headers
            return _make_response()

    patch_urllib3_urlopen(FakePool)
    monkeypatch.setattr(urllib3_patch_module, "_should_intercept_bedrock_request", lambda _: True)
    monkeypatch.setattr(urllib3_patch_module, "get_run_id", lambda: "run-1")
    monkeypatch.setattr(urllib3_patch_module, "find_source_nodes", lambda *args, **kwargs: [])
    monkeypatch.setattr(urllib3_patch_module, "store_output_strings", lambda *args, **kwargs: None)
    monkeypatch.setattr(urllib3_patch_module, "send_graph_node_and_edges", lambda *args, **kwargs: None)

    captured = {}

    def fake_get_in_out(input_dict, api_type):
        rewritten = dict(input_dict)
        rewritten["body"] = b'{"messages":[{"role":"user","content":[{"text":"Edited"}]}]}'
        rewritten["url"] = "/model/amazon.nova-lite-v1:0/converse"
        return CacheOutput(
            input_dict=rewritten,
            output=None,
            node_uuid="node-b",
            input_pickle=b"",
            input_hash="hash",
            run_id="run-1",
            stack_trace="stack",
        )

    def fake_prepare_replayed_request(input_dict, original_request):
        captured["original_request"] = dict(original_request)
        captured["rewritten_body"] = input_dict["body"]
        input_dict["url"] = "/model/amazon.nova-lite-v1%3A0/converse"
        input_dict["full_url"] = (
            "https://bedrock-runtime.us-east-1.amazonaws.com/model/amazon.nova-lite-v1%3A0/converse"
        )
        input_dict["headers"] = {"Authorization": "fresh"}
        return input_dict

    monkeypatch.setattr(urllib3_patch_module.DB, "get_in_out", fake_get_in_out)
    monkeypatch.setattr(
        urllib3_patch_module.DB,
        "cache_output",
        lambda cache_result, output_obj, api_type, cache=True: setattr(cache_result, "output", output_obj),
    )
    monkeypatch.setattr(urllib3_patch_module, "_prepare_replayed_request", fake_prepare_replayed_request)

    pool = FakePool()
    pool.urlopen(
        "POST",
        "/model/amazon.nova-lite-v1%3A0/converse",
        body=_bedrock_input_dict()["body"],
        headers={"content-type": "application/json"},
    )

    assert pool.original_calls == 1
    assert captured["original_request"]["url"].endswith("/model/amazon.nova-lite-v1%3A0/converse")
    assert captured["rewritten_body"] == b'{"messages":[{"role":"user","content":[{"text":"Edited"}]}]}'
    assert pool.last_url.endswith("/model/amazon.nova-lite-v1%3A0/converse")
    assert pool.last_headers["Authorization"] == "fresh"


def test_patch_urllib3_urlopen_returns_cached_response_without_calling_network(monkeypatch):
    class FakePool:
        scheme = "https"
        host = "bedrock-runtime.us-east-1.amazonaws.com"
        port = 443

        def __init__(self):
            self.original_calls = 0

        def urlopen(self, method, url, body=None, headers=None, **kwargs):
            self.original_calls += 1
            return _make_response()

    patch_urllib3_urlopen(FakePool)
    monkeypatch.setattr(urllib3_patch_module, "_should_intercept_bedrock_request", lambda _: True)
    monkeypatch.setattr(urllib3_patch_module, "get_run_id", lambda: "run-1")
    monkeypatch.setattr(urllib3_patch_module, "find_source_nodes", lambda *args, **kwargs: [])

    cached_response = _make_response()

    monkeypatch.setattr(
        urllib3_patch_module.DB,
        "get_in_out",
        lambda input_dict, api_type: CacheOutput(
            input_dict=input_dict,
            output=cached_response,
            node_uuid="node-b",
            input_pickle=b"",
            input_hash="hash",
            run_id="run-1",
            stack_trace="stack",
        ),
    )
    monkeypatch.setattr(urllib3_patch_module.DB, "cache_output", lambda *args, **kwargs: pytest.fail("cache_output should not run on cache hits"))
    monkeypatch.setattr(urllib3_patch_module, "store_output_strings", lambda *args, **kwargs: None)
    monkeypatch.setattr(urllib3_patch_module, "send_graph_node_and_edges", lambda *args, **kwargs: None)

    pool = FakePool()
    response = pool.urlopen(
        "POST",
        "/model/amazon.nova-lite-v1%3A0/converse",
        body=_bedrock_input_dict()["body"],
        headers={"content-type": "application/json"},
    )

    assert pool.original_calls == 0
    assert response is cached_response
