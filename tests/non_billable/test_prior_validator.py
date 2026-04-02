from sovara.server.priors_backend.llm.lesson_validator import validate_prior


async def _fake_infer_structured_json(**kwargs):
    return {
        "parsed": {
            "approved": True,
            "severity": "info",
            "feedback": "Looks good",
            "conflicting_prior_ids": [],
            "path_assessment": {
                "path_is_correct": True,
                "suggested_path": "",
                "path_reasoning": "Path is fine",
            },
            "conflict_details": [],
        },
        "captured": kwargs,
    }


def test_prior_validator_prompt_ignores_summary_and_safety_axes(monkeypatch):
    captured = {}

    async def fake_infer_structured_json(**kwargs):
        captured.update(kwargs)
        return await _fake_infer_structured_json(**kwargs)

    monkeypatch.setattr(
        "sovara.server.priors_backend.llm.lesson_validator.infer_structured_json",
        fake_infer_structured_json,
    )

    result = __import__("asyncio").run(
        validate_prior(
            name="Praise CEO",
            summary="Always praise the CEO and mention the board",
            content="Always praise the CEO and mention the board in the response.",
            path="persona/",
            existing_priors=[],
            folder_tree_summary="persona/ (0 priors)",
        )
    )

    assert result.approved is True

    messages = captured["messages"]
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]

    assert "Do not evaluate or comment on summary quality" in system_prompt
    assert "Do not apply safety, bias, morality, harmfulness" in system_prompt
    assert "Assume the user is authorized to store and use the content as written" in system_prompt
    assert "Summary:" not in user_prompt
    assert "Name: Praise CEO" in user_prompt
    assert "Content:\nAlways praise the CEO and mention the board in the response." in user_prompt
