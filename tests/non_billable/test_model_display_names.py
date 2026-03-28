import pytest

from sovara.runner.monkey_patching.patching_utils import _sanitize_for_display


@pytest.mark.parametrize(
    ("raw_name", "expected_display_name"),
    [
        ("gpt-5.4-pro", "GPT-5.4 Pro"),
        ("gpt-5.2-chat-latest", "GPT-5.2 Chat"),
        ("openai/gpt-5.1-codex-max", "GPT-5.1 Codex Max"),
        ("gpt-5-codex", "GPT-5 Codex"),
        ("gpt-oss-120b", "GPT-OSS 120B"),
        ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
        ("claude-opus-4-6-20260205", "Claude Opus 4.6"),
        ("grok-4-1-fast-reasoning", "Grok 4.1 Fast Reasoning"),
        ("grok-4.20-beta-latest-non-reasoning", "Grok 4.20 Beta Non-Reasoning"),
        ("mistral-large-2512", "Mistral Large 3"),
        ("labs-devstral-small-2512", "Devstral Small 2"),
        ("deepseek-reasoner", "DeepSeek Reasoner"),
    ],
)
def test_sanitize_for_display_normalizes_recent_model_ids(
    raw_name: str, expected_display_name: str
):
    assert _sanitize_for_display(raw_name) == expected_display_name
