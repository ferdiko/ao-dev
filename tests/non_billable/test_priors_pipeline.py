from sovara.runner.priors_pipeline import (
    extract_prompt_bearing_keys,
    extract_prompt_bearing_pairs,
    flatten_complete_to_show,
    inject_priors_block,
    render_retrieval_context,
    replay_injected_prefix,
    restore_to_show_from_flattened,
    strip_priors_from_flattened,
)


def test_flatten_complete_to_show_and_restore_round_trip_lists():
    to_show = {
        "body.system": "You are helpful.",
        "body.messages": [
            {"role": "user", "content": "Try retries"},
            {"role": "assistant", "content": "Okay"},
        ],
    }

    flattened = flatten_complete_to_show(to_show)

    assert flattened["body.system"] == "You are helpful."
    assert flattened["body.messages.0.role"] == "user"
    assert flattened["body.messages.1.content"] == "Okay"
    assert restore_to_show_from_flattened(flattened) == to_show


def test_strip_priors_from_flattened_extracts_manifest_ids_and_warns_on_manual_blocks():
    flattened = {
        "body.system": (
            "<sovara-priors>\n"
            '<!-- {"priors":[{"id":"p1"},{"id":"p2","fp":"sha256:abc"}]} -->\n'
            "## Retry\nRetry once.\n"
            "</sovara-priors>\n\n"
            "You are helpful."
        ),
        "body.messages.0.content": "<sovara-priors>\n## Manual\nNo manifest\n</sovara-priors>\n\nQuestion",
    }

    cleaned, inherited_prior_ids, warnings = strip_priors_from_flattened(flattened)

    assert inherited_prior_ids == ["p1", "p2"]
    assert cleaned["body.system"] == "You are helpful."
    assert cleaned["body.messages.0.content"] == "Question"
    assert warnings == ["Stripped a manual <sovara-priors> block without a manifest."]


def test_extract_prompt_bearing_keys_in_order_without_role_fields():
    flattened = {
        "body.messages.1.role": "assistant",
        "body.messages.1.content": "Answer",
        "body.messages.0.role": "user",
        "body.messages.0.content": "Question",
        "body.system": "You are helpful.",
        "body.temperature": 0,
    }

    assert extract_prompt_bearing_keys(flattened, "httpx.Client.send") == [
        "body.system",
        "body.messages.0.content",
        "body.messages.1.content",
    ]
    assert extract_prompt_bearing_pairs(flattened, "httpx.Client.send") == [
        {"key": "body.system", "value": "You are helpful."},
        {"key": "body.messages.0.content", "value": "Question"},
        {"key": "body.messages.1.content", "value": "Answer"},
    ]


def test_replay_injected_prefix_replaces_prompt_pair_values():
    flattened = {
        "body.system": "System",
        "body.messages.0.content": "Question",
        "body.messages.1.content": "Answer",
    }

    replayed = replay_injected_prefix(
        flattened,
        [
            {"key": "body.system", "value": "<sovara-priors>\n...\n</sovara-priors>\n\nSystem"},
            {"key": "body.messages.0.content", "value": "Question"},
        ],
    )

    assert replayed["body.system"].startswith("<sovara-priors>")
    assert replayed["body.messages.1.content"] == "Answer"


def test_render_retrieval_context_serializes_suffix_pairs():
    suffix_pairs = [
        {"key": "body.messages.2.content", "value": "New assistant reply"},
        {"key": "body.messages.3.content", "value": "Follow-up question"},
    ]

    assert render_retrieval_context(suffix_pairs) == (
        "body.messages.2.content: New assistant reply\n"
        "body.messages.3.content: Follow-up question"
    )


def test_inject_priors_block_prepends_to_target_key():
    flattened = {"body.messages.2.content": "Question"}
    injected = inject_priors_block(
        flattened,
        "<sovara-priors>\n<!-- {\"priors\":[]} -->\n</sovara-priors>",
        {"key": "body.messages.2.content"},
    )

    assert injected["body.messages.2.content"].startswith("<sovara-priors>")
    assert injected["body.messages.2.content"].endswith("Question")
