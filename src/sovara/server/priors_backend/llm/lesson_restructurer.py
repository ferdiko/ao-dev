"""LLM-based prior restructuring using the internal structured LLM bridge."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from sovara.server.priors_backend.llm.lesson_retriever import build_folder_tree_summary, collect_folder_priors
from sovara.server.priors_backend.llm_client import infer_structured_json
from sovara.server.priors_backend.logger import logger

_RESTRUCTURE_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "prior_restructure",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "new_folders": {"type": "array", "items": {"type": "string"}},
                "removed_folders": {"type": "array", "items": {"type": "string"}},
                "moves": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "prior_id": {"type": "string"},
                            "current_path": {"type": "string"},
                            "new_path": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["prior_id", "current_path", "new_path", "reason"],
                        "additionalProperties": False,
                    },
                },
                "redundant_prior_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "new_folders", "removed_folders", "moves", "redundant_prior_ids"],
            "additionalProperties": False,
        },
    },
}


@dataclass
class PriorMove:
    prior_id: str
    current_path: str
    new_path: str
    reason: str


@dataclass
class RestructureProposal:
    summary: str
    new_folders: list[str]
    removed_folders: list[str]
    moves: list[PriorMove]
    redundant_prior_ids: list[str]


def _compute_snapshot(all_priors: dict[str, dict]) -> str:
    items = sorted(all_priors.items())
    parts = []
    for prior_id, prior in items:
        parts.append(f"{prior_id}:{prior.get('path', '')}:{prior.get('name', '')}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


async def propose_restructure(
    store,
    base_path: str = "",
    comments: Optional[str] = None,
) -> tuple[RestructureProposal, str, dict[str, dict]]:
    folder_priors, all_priors = collect_folder_priors(store, base_path)
    if not all_priors:
        return (
            RestructureProposal(
                summary="No priors found to restructure.",
                new_folders=[],
                removed_folders=[],
                moves=[],
                redundant_prior_ids=[],
            ),
            _compute_snapshot(all_priors),
            all_priors,
        )

    folder_tree = build_folder_tree_summary(store, base_path)
    snapshot = _compute_snapshot(all_priors)

    prior_lines = []
    for prior_id, prior in sorted(all_priors.items()):
        prior_lines.append(
            f"- ID: {prior_id} | Path: {prior.get('path', '(root)')} | "
            f"Name: {prior.get('name', '')} | Summary: {prior.get('summary', '')}"
        )

    prompt = (
        "Analyze the following prior collection and propose a better folder structure.\n\n"
        f"CURRENT FOLDER TREE:\n{folder_tree}\n\n"
        f"PRIORS:\n{chr(10).join(prior_lines)}\n\n"
        "Propose a restructured folder organization. For each prior that should move, specify the move.\n"
        "Mark redundant priors that could potentially be deleted after human review."
    )
    if comments:
        prompt += f"\n\nUSER GUIDANCE:\n{comments}"

    result = await infer_structured_json(
        tier="expensive",
        response_format=_RESTRUCTURE_RESPONSE_SCHEMA,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a prior taxonomy expert. Group priors semantically, minimize churn, "
                    "and prefer a shallow but meaningful folder hierarchy."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        timeout_ms=30000,
        repair_attempts=2,
    )
    parsed = result["parsed"]
    proposal = RestructureProposal(
        summary=parsed["summary"],
        new_folders=list(parsed["new_folders"]),
        removed_folders=list(parsed["removed_folders"]),
        moves=[PriorMove(**move) for move in parsed["moves"]],
        redundant_prior_ids=list(parsed["redundant_prior_ids"]),
    )
    logger.info(
        "Restructure proposal for '%s': %s moves, %s new folders, %s redundant",
        base_path or "(root)",
        len(proposal.moves),
        len(proposal.new_folders),
        len(proposal.redundant_prior_ids),
    )
    return proposal, snapshot, all_priors


async def execute_restructure(store, proposal: RestructureProposal, expected_snapshot: str, base_path: str = "") -> dict:
    _, all_priors = collect_folder_priors(store, base_path)
    current_snapshot = _compute_snapshot(all_priors)
    if current_snapshot != expected_snapshot:
        raise ValueError(
            f"Priors have changed since the proposal was generated. Expected snapshot {expected_snapshot}, got {current_snapshot}."
        )

    created_folders: set[str] = set()
    moved_count = 0
    move_log: list[dict] = []

    for folder in proposal.new_folders:
        store.create_folder(folder)
        created_folders.add(folder)

    for move in proposal.moves:
        if move.new_path and move.new_path not in created_folders:
            store.create_folder(move.new_path)
            created_folders.add(move.new_path)
        result = store.move_lessons([move.prior_id], move.new_path)
        if result.get("moved_count", 0) > 0:
            moved_count += 1
            move_log.append(
                {
                    "prior_id": move.prior_id,
                    "from": move.current_path,
                    "to": move.new_path,
                    "reason": move.reason,
                }
            )

    return {
        "status": "completed",
        "moved_count": moved_count,
        "created_folders": sorted(created_folders),
        "move_log": move_log,
    }
