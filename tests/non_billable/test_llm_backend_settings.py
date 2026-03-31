from types import SimpleNamespace

from sovara.server import llm_backend


def _fake_response():
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        model="unused",
    )


def test_infer_uses_hosted_vllm_api_base(monkeypatch):
    recorded: dict = {}

    def fake_completion(**kwargs):
        recorded.update(kwargs)
        return _fake_response()

    monkeypatch.setattr(llm_backend, "read_user_id", lambda: "user-1")
    monkeypatch.setattr(
        llm_backend.DB,
        "get_user",
        lambda user_id: {
            "llm_primary_provider": "hosted_vllm",
            "llm_primary_model_name": "Meta-Llama-3.1-70B-Instruct",
            "llm_primary_api_base": "http://192.168.1.50:8000/v1",
            "llm_helper_provider": "together",
            "llm_helper_model_name": "Qwen/Qwen3.5-9B",
            "llm_helper_api_base": None,
        },
    )
    monkeypatch.setattr(llm_backend.litellm, "completion", fake_completion)

    llm_backend.infer([{"role": "user", "content": "hello"}], tier="expensive")

    assert recorded["model"] == "hosted_vllm/Meta-Llama-3.1-70B-Instruct"
    assert recorded["api_base"] == "http://192.168.1.50:8000/v1"


def test_infer_drops_provider_specific_extra_body_for_anthropic(monkeypatch):
    recorded: dict = {}

    def fake_completion(**kwargs):
        recorded.update(kwargs)
        return _fake_response()

    monkeypatch.setattr(llm_backend, "read_user_id", lambda: "user-1")
    monkeypatch.setattr(
        llm_backend.DB,
        "get_user",
        lambda user_id: {
            "llm_primary_provider": "anthropic",
            "llm_primary_model_name": "claude-sonnet-4-5",
            "llm_primary_api_base": None,
            "llm_helper_provider": "anthropic",
            "llm_helper_model_name": "claude-haiku-4-5",
            "llm_helper_api_base": None,
        },
    )
    monkeypatch.setattr(llm_backend.litellm, "completion", fake_completion)

    llm_backend.infer(
        [{"role": "user", "content": "hello"}],
        tier="expensive",
        extra_body=llm_backend.NO_THINKING_EXTRA_BODY,
    )

    assert recorded["model"] == "anthropic/claude-sonnet-4-5"
    assert "extra_body" not in recorded
