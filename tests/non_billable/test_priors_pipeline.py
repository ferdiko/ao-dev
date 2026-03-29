from sovara.runner.priors_pipeline import (
    build_input_delta,
    flatten_complete_to_show,
    inject_priors_block,
    render_retrieval_context,
    resolve_injection_anchor,
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


def test_build_input_delta_compares_values_across_all_parent_entries():
    current = {
        "body.messages.0.role": "user",
        "body.messages.0.content": "Try retries on timeout",
        "body.system": "Be concise",
    }
    parent_a = {
        "body.messages.0.role": "user",
        "body.messages.0.content": "Old question",
    }
    parent_b = {
        "body.system": "Be concise",
    }

    delta = build_input_delta(current, [parent_a, parent_b])

    assert delta == [{"key": "body.messages.0.content", "value": "Try retries on timeout"}]
    assert render_retrieval_context(delta) == "body.messages.0.content: Try retries on timeout"


def test_resolve_injection_anchor_prefers_system_and_falls_back_to_first_prompt_field():
    with_system = {
        "body.system": "You are helpful.",
        "body.messages.0.content": "Question",
    }
    without_system = {
        "body.messages.0.content": "Question",
        "body.messages.1.content": "Earlier assistant reply",
    }

    assert resolve_injection_anchor(with_system, "httpx.Client.send") == {"key": "body.system"}
    assert resolve_injection_anchor(without_system, "httpx.Client.send") == {"key": "body.messages.0.content"}


def test_inject_priors_block_prepends_to_resolved_anchor():
    flattened = {"body.messages.0.content": "Question"}
    injected = inject_priors_block(
        flattened,
        "<sovara-priors>\n<!-- {\"priors\":[]} -->\n</sovara-priors>",
        {"key": "body.messages.0.content"},
    )

    assert injected["body.messages.0.content"].startswith("<sovara-priors>")
    assert injected["body.messages.0.content"].endswith("Question")
