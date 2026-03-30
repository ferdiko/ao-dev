import json
import uuid
from datetime import datetime, timezone

import httpx

from sovara.common.constants import TEST_PROJECT_ID, TEST_USER_ID
from sovara.runner.monkey_patching.patching_utils import get_node_kind
from sovara.server.database_manager import DB


class _FakeUrl:
    def __init__(self, url: str, path: str):
        self._url = url
        self.path = path

    def __str__(self) -> str:
        return self._url


class _FakeHttpxRequest:
    def __init__(self, url: str, path: str):
        self.url = _FakeUrl(url, path)
        self.content = b'{"model":"gpt-5.4"}'


def _seed_run(run_id: str) -> None:
    DB.add_run(
        run_id=run_id,
        name="Schema Seed",
        timestamp=datetime.now(timezone.utc),
        cwd="/tmp",
        command="python -m test.workflow",
        environment={},
        project_id=TEST_PROJECT_ID,
        user_id=TEST_USER_ID,
    )


def _make_httpx_input(instructions: str) -> dict:
    return {
        "request": httpx.Request(
            "POST",
            "https://api.openai.com/v1/responses",
            json={"model": "gpt-5.4", "instructions": instructions},
        )
    }


def test_copy_llm_calls_preserves_node_kind_and_input_delta():
    old_run_id = str(uuid.uuid4())
    new_run_id = str(uuid.uuid4())
    node_uuid = str(uuid.uuid4())
    _seed_run(old_run_id)
    _seed_run(new_run_id)

    try:
        DB.backend.insert_llm_call_with_output_query(
            old_run_id,
            json.dumps({"raw": {"body": {}}, "to_show": {"body": {"messages": ["hello"]}}}),
            "hash-1",
            node_uuid,
            "httpx.Client.send",
            json.dumps({"raw": {"content": "ok"}, "to_show": {"content": "ok"}}),
            "stack line",
            "tool",
            json.dumps([{"key": "body.messages.0", "value": "hello"}]),
        )

        DB.copy_llm_calls(old_run_id, new_run_id)
        copied = dict(DB.get_llm_call_full(new_run_id, node_uuid))

        assert copied["node_kind"] == "tool"
        assert json.loads(copied["input_delta_json"]) == [{"key": "body.messages.0", "value": "hello"}]
    finally:
        DB.backend.delete_runs_by_ids_query([old_run_id, new_run_id], user_id=None)
        DB._occurrence_counters.clear()


def test_prior_retrieval_roundtrip_and_copy():
    old_run_id = str(uuid.uuid4())
    new_run_id = str(uuid.uuid4())
    node_uuid = str(uuid.uuid4())
    _seed_run(old_run_id)
    _seed_run(new_run_id)

    try:
        DB.backend.insert_llm_call_with_output_query(
            old_run_id,
            json.dumps({"raw": {"body": {}}, "to_show": {"body": {"messages": ["hello"]}}}),
            "hash-2",
            node_uuid,
            "httpx.Client.send",
            json.dumps({"raw": {"content": "ok"}, "to_show": {"content": "ok"}}),
            "stack line",
            "llm",
            "[]",
        )
        DB.copy_llm_calls(old_run_id, new_run_id)

        DB.upsert_prior_retrieval(
            old_run_id,
            node_uuid,
            retrieval_context="body.messages.0.content: hello",
            inherited_prior_ids=["p-old"],
            applied_priors=[{"id": "p-new", "content": "Retry once"}],
            rendered_priors_block="<sovara-priors>...</sovara-priors>",
            injection_anchor={"key": "body.messages.0.content"},
            model="qwen3.5",
            timeout_ms=30000,
            latency_ms=142,
        )

        stored = DB.get_prior_retrieval(old_run_id, node_uuid)
        assert stored["inherited_prior_ids"] == ["p-old"]
        assert stored["applied_priors"] == [{"id": "p-new", "content": "Retry once"}]
        assert stored["injection_anchor"] == {"key": "body.messages.0.content"}

        DB.copy_prior_retrievals(old_run_id, new_run_id)
        copied = DB.get_prior_retrieval(new_run_id, node_uuid)
        assert copied["run_id"] == new_run_id
        assert copied["model"] == "qwen3.5"
    finally:
        DB.backend.delete_runs_by_ids_query([old_run_id, new_run_id], user_id=None)
        DB._occurrence_counters.clear()


def test_get_node_kind_classifies_llm_mcp_and_tool_calls():
    llm_input = {
        "request": _FakeHttpxRequest("https://api.openai.com/v1/responses", "/v1/responses")
    }
    tool_input = {
        "request": _FakeHttpxRequest("https://google.serper.dev/search", "/search")
    }
    embedding_input = {
        "request": _FakeHttpxRequest("http://localhost:11434/api/embeddings", "/api/embeddings")
    }

    assert get_node_kind(llm_input, "httpx.Client.send") == "llm"
    assert get_node_kind(tool_input, "httpx.Client.send") == "tool"
    assert get_node_kind(embedding_input, "httpx.Client.send") == "tool"
    assert get_node_kind({"request": object()}, "MCP.ClientSession.send_request") == "mcp"
    assert get_node_kind({"tool_name": "search"}, "claude_agent_sdk.parse_message") == "tool"
    assert get_node_kind({"model": "claude-sonnet"}, "claude_agent_sdk.parse_message") == "llm"


def test_get_in_out_hashes_and_stores_executed_input(monkeypatch):
    run_id = str(uuid.uuid4())
    _seed_run(run_id)
    monkeypatch.setattr("sovara.runner.context_manager.get_run_id", lambda: run_id)

    clean_input = _make_httpx_input("Answer briefly.")
    executed_input = _make_httpx_input(
        "<sovara-priors>\n<!-- {\"priors\":[{\"id\":\"p1\"}]} -->\n## Retry\nRetry once.\n</sovara-priors>\n\nAnswer briefly."
    )

    try:
        cache_output = DB.get_in_out(executed_input, "httpx.Client.send")
        clean_hash_output = DB.get_in_out(clean_input, "httpx.Client.send")

        assert cache_output.input_hash != clean_hash_output.input_hash

        response = httpx.Response(
            200,
            request=cache_output.input_dict["request"],
            json={"ok": True},
        )
        DB.cache_output(cache_output, response, "httpx.Client.send")

        stored = dict(DB.get_llm_call_full(run_id, cache_output.node_uuid))
        stored_input = json.loads(stored["input"])

        assert stored["input_hash"] == cache_output.input_hash
        assert stored_input["to_show"]["body.instructions"].startswith("<sovara-priors>")
        assert stored_input["to_show"]["body.instructions"].endswith("Answer briefly.")
    finally:
        DB.backend.delete_runs_by_ids_query([run_id], user_id=None)
        DB._occurrence_counters.clear()
