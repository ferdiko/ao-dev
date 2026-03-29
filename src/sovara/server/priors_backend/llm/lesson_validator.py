"""LLM-based prior validation using the internal structured LLM bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from sovara.server.priors_backend.llm_client import infer_structured_json
from sovara.server.priors_backend.logger import logger

_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "prior_validation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "approved": {"type": "boolean"},
                "severity": {"type": "string", "enum": ["info", "warning", "error"]},
                "feedback": {"type": "string"},
                "conflicting_prior_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "path_assessment": {
                    "type": "object",
                    "properties": {
                        "path_is_correct": {"type": "boolean"},
                        "suggested_path": {"type": "string"},
                        "path_reasoning": {"type": "string"},
                    },
                    "required": ["path_is_correct", "suggested_path", "path_reasoning"],
                    "additionalProperties": False,
                },
                "conflict_details": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "prior_id": {"type": "string"},
                            "conflict_type": {
                                "type": "string",
                                "enum": ["contradiction", "redundancy", "superseded"],
                            },
                            "explanation": {"type": "string"},
                            "resolution_suggestion": {"type": "string"},
                        },
                        "required": ["prior_id", "conflict_type", "explanation", "resolution_suggestion"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "approved",
                "severity",
                "feedback",
                "conflicting_prior_ids",
                "path_assessment",
                "conflict_details",
            ],
            "additionalProperties": False,
        },
    },
}


@dataclass
class PathAssessment:
    path_is_correct: bool
    suggested_path: str
    path_reasoning: str


@dataclass
class ConflictDetail:
    prior_id: str
    conflict_type: str
    explanation: str
    resolution_suggestion: str
    creation_trace_id: Optional[str] = None


@dataclass
class ValidationResult:
    approved: bool
    feedback: str
    severity: str
    conflicting_prior_ids: List[str]
    path_assessment: Optional[PathAssessment] = None
    conflict_details: List[ConflictDetail] = field(default_factory=list)


async def validate_prior(
    name: str,
    summary: str,
    content: str,
    path: str,
    existing_priors: List[dict],
    existing_prior_id: Optional[str] = None,
    folder_tree_summary: Optional[str] = None,
    model: str = "openai/gpt-5.4",
) -> ValidationResult:
    # The summary is generated separately after approval, so validation should
    # not evaluate or comment on summary quality.
    _ = summary
    if existing_prior_id:
        existing_priors = [prior for prior in existing_priors if prior.get("id") != existing_prior_id]

    existing_context = []
    for prior in existing_priors:
        existing_context.append(
            f"--- Prior (ID: {prior.get('id')}): {prior.get('name', 'Untitled')} ---\n"
            f"Summary: {prior.get('summary', 'No summary')}\n"
            f"Content:\n{prior.get('content', 'No content')}"
        )
    existing_context_text = "\n\n".join(existing_context) if existing_context else "(No existing priors in this folder)"

    folder_tree_section = (
        f"FOLDER TREE:\n{folder_tree_summary}"
        if folder_tree_summary
        else "No folder tree provided. Assume the proposed path is acceptable unless clearly wrong."
    )

    system_prompt = """You are a critical prior quality reviewer.

Evaluate only:
1. internal quality, clarity, and specificity of the prior content
2. consistency with existing priors
3. redundancy, contradiction, and supersession
4. path correctness

Important constraints:
- Do not evaluate or comment on summary quality. Summaries are generated separately after approval.
- Do not apply safety, bias, morality, harmfulness, offensiveness, ideology, or persuasion review.
- Assume the user is authorized to store and use the content as written.
- Focus only on whether the prior is technically useful, clear, non-duplicative, internally consistent, and correctly placed.

Be constructive but rigorous. Most priors should be approved with useful feedback.
Reject only for severe problems in quality, conflict, redundancy, or placement."""

    user_prompt = f"""Please analyze the following proposed prior.

Name: {name}
Content:
{content}

Path: {path or "(root)"}

Existing priors:
{existing_context_text}

{folder_tree_section}
"""

    try:
        result = await infer_structured_json(
            purpose="priors_validation",
            model=model,
            tier="expensive",
            response_format=_RESPONSE_SCHEMA,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout_ms=30000,
            repair_attempts=2,
        )
        parsed = result["parsed"]
        path_assessment = PathAssessment(**parsed["path_assessment"])
        conflict_details = [ConflictDetail(**detail) for detail in parsed["conflict_details"]]
        prior_lookup = {prior.get("id"): prior for prior in existing_priors}
        for detail in conflict_details:
            conflicting = prior_lookup.get(detail.prior_id)
            if conflicting and conflicting.get("creation_trace_id"):
                detail.creation_trace_id = conflicting["creation_trace_id"]

        return ValidationResult(
            approved=parsed["approved"],
            feedback=parsed["feedback"],
            severity=parsed["severity"],
            conflicting_prior_ids=parsed.get("conflicting_prior_ids", []),
            path_assessment=path_assessment,
            conflict_details=conflict_details,
        )
    except Exception as exc:
        logger.error("Prior validation failed: %s", exc)
        return ValidationResult(
            approved=True,
            feedback=f"Validation failed with error: {exc}. Proceeding anyway.",
            severity="warning",
            conflicting_prior_ids=[],
        )
