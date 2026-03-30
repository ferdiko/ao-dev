import json

import httpx

from sovara.runner import priors as priors_runtime
from sovara.runner.monkey_patching.api_parser import func_kwargs_to_json_str
from sovara.runner.priors_pipeline import flatten_complete_to_show


def _make_responses_input(instructions: str) -> dict:
    return {
        "request": httpx.Request(
            "POST",
            "https://api.openai.com/v1/responses",
            json={"model": "gpt-5.4", "instructions": instructions},
        )
    }


def _make_chat_input(messages: list[dict[str, str]]) -> dict:
    return {
        "request": httpx.Request(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": messages},
        )
    }


def test_prepare_llm_call_for_priors_strips_manual_priors_and_retrieves_on_suffix(monkeypatch):
    inherited_block = (
        "<sovara-priors>\n"
        '<!-- {"priors":[{"id":"p-old"}]} -->\n'
        "## Existing\nAlready known.\n"
        "</sovara-priors>\n\n"
        "New ask"
    )
    input_dict = _make_responses_input(inherited_block)
    captured = {"calls": []}

    monkeypatch.setattr(priors_runtime, "get_run_id", lambda: "run-123")

    def fake_http_post(endpoint, data, timeout=None):
        captured["calls"].append((endpoint, data, timeout))
        if endpoint == "/internal/priors/prefix-cache/lookup":
            return {"found": False}
        if endpoint == "/internal/priors/retrieve":
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
        if endpoint == "/internal/priors/prefix-cache/store":
            return {"stored": True}
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(priors_runtime, "http_post", fake_http_post)

    result = priors_runtime.prepare_llm_call_for_priors(input_dict, "httpx.Client.send")
    executed_payload = json.loads(func_kwargs_to_json_str(result.executed_input_dict, "httpx.Client.send")[0])
    executed_flattened = flatten_complete_to_show(executed_payload["to_show"])
    executed_flattened = flatten_complete_to_show(executed_payload["to_show"])

    assert json.loads(result.input_delta_json) == [{"key": "body.instructions", "value": "New ask"}]
    assert result.metadata.status == "applied"
    assert result.metadata.inherited_prior_ids == ["p-old"]
    assert result.metadata.model == "qwen3.5"
    assert executed_payload["to_show"]["body.instructions"].startswith("<sovara-priors>")
    assert executed_payload["to_show"]["body.instructions"].endswith("New ask")
    assert captured["calls"][0][0] == "/internal/priors/prefix-cache/lookup"
    assert captured["calls"][1][0] == "/internal/priors/retrieve"
    assert captured["calls"][1][1]["ignore_prior_ids"] == ["p-old"]
    assert captured["calls"][1][1]["context"] == "body.instructions: New ask"
    assert captured["calls"][2][0] == "/internal/priors/prefix-cache/store"


def test_prepare_llm_call_for_priors_replays_cached_prefix_and_retrieves_only_suffix(monkeypatch):
    input_dict = _make_chat_input(
        [
            {"role": "developer", "content": "You are helpful."},
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
        ]
    )
    captured = {"calls": []}

    monkeypatch.setattr(priors_runtime, "get_run_id", lambda: "run-123")

    def fake_http_post(endpoint, data, timeout=None):
        captured["calls"].append((endpoint, data, timeout))
        if endpoint == "/internal/priors/prefix-cache/lookup":
            return {
                "found": True,
                "matched_pair_count": 2,
                "injected_pairs": [
                    {
                        "key": "body.messages.0.content",
                        "value": (
                            "<sovara-priors>\n"
                            '<!-- {"priors":[{"id":"p-old"}]} -->\n'
                            "## Existing\nAlready known.\n"
                            "</sovara-priors>\n\n"
                            "You are helpful."
                        ),
                    },
                    {"key": "body.messages.1.content", "value": "Question"},
                ],
                "prior_ids": ["p-old"],
            }
        if endpoint == "/internal/priors/retrieve":
            assert data["ignore_prior_ids"] == ["p-old"]
            assert data["context"] == "body.messages.2.content: Answer"
            return {
                "priors": [],
                "rendered_priors_block": "",
                "model_used": "openai/gpt-5.4-mini",
            }
        if endpoint == "/internal/priors/prefix-cache/store":
            return {"stored": True}
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(priors_runtime, "http_post", fake_http_post)

    result = priors_runtime.prepare_llm_call_for_priors(input_dict, "httpx.Client.send")
    executed_payload = json.loads(func_kwargs_to_json_str(result.executed_input_dict, "httpx.Client.send")[0])
    executed_flattened = flatten_complete_to_show(executed_payload["to_show"])

    assert json.loads(result.input_delta_json) == [
        {"key": "body.messages.2.content", "value": "Answer"}
    ]
    assert result.metadata.status == "none"
    assert result.metadata.inherited_prior_ids == ["p-old"]
    assert executed_flattened["body.messages.0.content"].startswith("<sovara-priors>")
    assert executed_flattened["body.messages.2.content"] == "Answer"
    assert [call[0] for call in captured["calls"]] == [
        "/internal/priors/prefix-cache/lookup",
        "/internal/priors/retrieve",
        "/internal/priors/prefix-cache/store",
    ]
