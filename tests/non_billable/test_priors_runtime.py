import json

import httpx

from sovara.runner import priors as priors_runtime
from sovara.runner.monkey_patching.api_parser import func_kwargs_to_json_str


def _make_httpx_input(instructions: str) -> dict:
    return {
        "request": httpx.Request(
            "POST",
            "https://api.openai.com/v1/responses",
            json={"model": "gpt-5.4", "instructions": instructions},
        )
    }


def test_prepare_llm_call_for_priors_returns_clean_display_and_injected_execution(monkeypatch):
    inherited_block = (
        "<sovara-priors>\n"
        '<!-- {"priors":[{"id":"p-old"}]} -->\n'
        "## Existing\nAlready known.\n"
        "</sovara-priors>\n\n"
        "New ask"
    )
    input_dict = _make_httpx_input(inherited_block)
    captured = {}

    monkeypatch.setattr(priors_runtime, "get_run_id", lambda: "run-123")
    monkeypatch.setattr(
        priors_runtime,
        "find_source_nodes",
        lambda run_id, clean_input_dict, api_type: ["parent-node"],
    )
    monkeypatch.setattr(
        priors_runtime,
        "_effective_parent_flattened_inputs",
        lambda run_id, parent_node_ids: [
            {
                "url": "https://api.openai.com/v1/responses",
                "body.model": "gpt-5.4",
                "body.instructions": "Already known.",
            }
        ],
    )

    def fake_http_post(endpoint, data, timeout=None):
        captured["endpoint"] = endpoint
        captured["data"] = data
        captured["timeout"] = timeout
        return {
            "priors": [
                {
                    "id": "p-new",
                    "name": "Retry",
                    "summary": "Retry once",
                    "content": "Retry once with a short backoff.",
                    "path": "",
                }
            ],
            "rendered_priors_block": (
                "<sovara-priors>\n"
                '<!-- {"priors":[{"id":"p-new"}]} -->\n'
                "## Retry\nRetry once with a short backoff.\n"
                "</sovara-priors>"
            ),
            "model_used": "qwen3.5",
        }

    monkeypatch.setattr(priors_runtime, "http_post", fake_http_post)

    result = priors_runtime.prepare_llm_call_for_priors(input_dict, "httpx.Client.send")

    clean_payload = json.loads(func_kwargs_to_json_str(result.display_input_dict, "httpx.Client.send")[0])
    executed_payload = json.loads(func_kwargs_to_json_str(result.executed_input_dict, "httpx.Client.send")[0])

    assert result.source_node_ids == ["parent-node"]
    assert json.loads(result.input_delta_json) == [{"key": "body.instructions", "value": "New ask"}]
    assert result.metadata.status == "applied"
    assert result.metadata.inherited_prior_ids == ["p-old"]
    assert result.metadata.model == "qwen3.5"
    assert clean_payload["to_show"]["body.instructions"] == "New ask"
    assert executed_payload["to_show"]["body.instructions"].startswith("<sovara-priors>")
    assert executed_payload["to_show"]["body.instructions"].endswith("New ask")
    assert captured["endpoint"] == "/internal/priors/retrieve"
    assert captured["data"]["ignore_prior_ids"] == ["p-old"]
    assert captured["data"]["context"] == "body.instructions: New ask"
