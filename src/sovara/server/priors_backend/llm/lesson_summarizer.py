"""LLM-based prior summary generation with a safe local fallback."""

from __future__ import annotations

import re

from sovara.server.priors_backend.llm_client import infer_structured_json
from sovara.server.priors_backend.logger import logger

_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "prior_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
            },
            "required": ["summary"],
            "additionalProperties": False,
        },
    },
}


def _strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_>#-]+", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fallback_prior_summary(*, name: str, content: str) -> str:
    cleaned = _strip_markdown(content)
    if not cleaned:
        return f"Prior for {name}."
    sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0].strip()
    candidate = sentence or cleaned
    if len(candidate) <= 180:
        return candidate
    return candidate[:177].rstrip() + "..."


async def generate_prior_summary(
    *,
    name: str,
    content: str,
    path: str,
) -> str:
    system_prompt = """You write short, precise summaries for priors.

Return a single sentence summary that captures the main guidance in the prior.
Keep it concise and concrete. Do not mention formatting, markdown, or file names."""

    user_prompt = f"""Generate a short summary for this prior.

Name: {name}
Path: {path or "(root)"}
Content:
{content}
"""

    try:
        result = await infer_structured_json(
            tier="cheap",
            response_format=_RESPONSE_SCHEMA,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout_ms=15000,
            repair_attempts=2,
        )
        summary = str(result["parsed"]["summary"]).strip()
        return summary or fallback_prior_summary(name=name, content=content)
    except Exception as exc:
        logger.warning("Prior summary generation failed: %s", exc)
        return fallback_prior_summary(name=name, content=content)
