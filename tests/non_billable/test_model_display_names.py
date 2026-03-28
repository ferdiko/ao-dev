import pytest

from sovara.runner.monkey_patching.patching_utils import _sanitize_for_display


def test_openai_numeric_gpt_and_o_series_are_formatted_dynamically():
    assert _sanitize_for_display("gpt-5.2") == "GPT-5.2"
    assert _sanitize_for_display("gpt-5.2-pro") == "GPT-5.2 Pro"
    assert _sanitize_for_display("gpt-5.1-codex") == "GPT-5.1 Codex"
    assert _sanitize_for_display("gpt-5.1-codex-max") == "GPT-5.1 Codex Max"
    assert _sanitize_for_display("gpt-4-turbo") == "GPT-4 Turbo"
    assert _sanitize_for_display("gpt-4") == "GPT-4"
    assert _sanitize_for_display("gpt-3.5-turbo") == "GPT-3.5 Turbo"
    assert _sanitize_for_display("gpt-4o") == "GPT-4o"
    assert _sanitize_for_display("gpt-4o-mini-audio") == "GPT-4o Mini Audio"
    assert _sanitize_for_display("chatgpt-gpt-4o") == "GPT-4o"
    assert _sanitize_for_display("gpt-oss-120b") == "GPT-OSS 120B"
    assert _sanitize_for_display("o4-mini") == "o4 Mini"
    assert _sanitize_for_display("o3-pro") == "o3 Pro"


def test_anthropic_claude_models_strip_snapshot_dates_and_preserve_versions():
    assert _sanitize_for_display("claude-sonnet-4-6") == "Claude Sonnet 4.6"
    assert _sanitize_for_display("claude-opus-4-1-20250805") == "Claude Opus 4.1"
    assert _sanitize_for_display("claude-sonnet-4-20250514") == "Claude Sonnet 4"
    assert _sanitize_for_display("claude-3-7-sonnet-20250219") == "Claude 3.7 Sonnet"
    assert _sanitize_for_display("claude-3-5-haiku-latest") == "Claude 3.5 Haiku"


def test_gemini_models_render_with_clean_family_names():
    assert _sanitize_for_display("gemini-2.5-flash-lite") == "Gemini 2.5 Flash Lite"
    assert _sanitize_for_display("gemini-2.5-flash-lite-preview-09-2025") == "Gemini 2.5 Flash Lite Preview"
    assert _sanitize_for_display("gemini-1.5-pro") == "Gemini 1.5 Pro"


def test_open_weight_families_preserve_vendor_casing():
    assert _sanitize_for_display("Qwen3-Coder-480B-A35B-Instruct") == "Qwen3 Coder 480B A35B Instruct"
    assert _sanitize_for_display("QwQ-32B") == "QwQ 32B"
    assert _sanitize_for_display("Llama-4-Scout-17B-16E-Instruct") == "Llama 4 Scout 17B 16E Instruct"
    assert _sanitize_for_display("glm-4-9b-chat") == "GLM 4 9B Chat"
    assert _sanitize_for_display("Kimi-K2.5") == "Kimi K2.5"
    assert _sanitize_for_display("DeepSeek-R1-Distill-Qwen-32B") == "DeepSeek R1 Distill Qwen 32B"
    assert _sanitize_for_display("gemma-3-27b-it") == "Gemma 3 27B IT"
    assert _sanitize_for_display("Phi-4-mini-instruct") == "Phi 4 Mini Instruct"
    assert _sanitize_for_display("command-a-reasoning-08-2025") == "Command A Reasoning 08 2025"
    assert _sanitize_for_display("tiny-aya-earth") == "Tiny Aya Earth"
    assert _sanitize_for_display("granite-4.0-h-1b") == "Granite 4.0 H 1B"
    assert _sanitize_for_display("devstral-small-2505") == "Devstral Small 2505"


@pytest.mark.parametrize(
    ("raw_model_name", "expected_display_name"),
    [
        ("grok-4-0709", "Grok 4"),
        ("grok-4-latest", "Grok 4"),
        ("grok-4-fast-reasoning", "Grok 4 Fast"),
        ("grok-4-fast-non-reasoning", "Grok 4 Fast"),
        ("grok-4.20-beta-latest-non-reasoning", "Grok 4.20 Beta"),
        ("grok-4.20-multi-agent-beta-0309", "Grok 4.20 Multi-Agent Beta"),
        ("command-a-03-2025", "Command A"),
        ("amazon.nova-premier-v1:0", "Amazon Nova Premier"),
        ("us.amazon.nova-pro-v1:0", "Amazon Nova Pro"),
        ("amazon.nova-lite-v1:0", "Amazon Nova Lite"),
        ("amazon.nova-micro-v1:0", "Amazon Nova Micro"),
        ("amazon.nova-sonic-v1:0", "Amazon Nova Sonic"),
        ("amazon.nova-2-sonic-v1:0", "Amazon Nova 2 Sonic"),
        (
            "amazon.nova-2-multimodal-embeddings-v1:0",
            "Amazon Nova 2 Multimodal Embeddings",
        ),
        ("magistral-medium-2507", "Magistral Medium 1.1"),
        ("magistral-small-2507", "Magistral Small 1.1"),
    ],
)
def test_recent_model_display_aliases(raw_model_name: str, expected_display_name: str):
    assert _sanitize_for_display(raw_model_name) == expected_display_name
