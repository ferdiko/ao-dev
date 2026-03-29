"""Helpers for persisting trace chat edits back to the main server DB.

Calls the main server's /ui/edit-input endpoint so that DB write,
in-memory graph update, and WebSocket broadcast to the UI all happen
through the existing code path.
"""

import json
from dataclasses import dataclass

import httpx

from .prompt_sections import PromptSections
from .trace import Trace
from .text_paths import set_text_value

RERUN_MSG = "\n\nEdit applied and saved."


@dataclass
class PersistOutcome:
    ok: bool
    message: str = ""


def _read_to_show(run_id: str, node_uuid: str) -> dict | None:
    """Return the current to_show dict for a node, or None if unavailable."""
    from sovara.server.database_manager import DB
    row = DB.query_one_llm_call_input(run_id, node_uuid)
    if not row:
        return None
    inp = json.loads(dict(row)["input"] or "{}")
    return inp.get("to_show")


def _post_edit_input(run_id: str, node_uuid: str, to_show: dict) -> bool:
    """Call POST /ui/edit-input on the main server. Returns True on success."""
    from sovara.common.constants import HOST, PORT
    try:
        resp = httpx.post(
            f"http://{HOST}:{PORT}/ui/edit-input",
            json={"run_id": run_id, "node_uuid": node_uuid, "value": json.dumps(to_show)},
            timeout=10.0,
        )
        return resp.is_success
    except Exception:
        return False

def write_prompt_edit(trace: Trace, prompt_id: str, path: str, codec: str, new_text: str) -> PersistOutcome:
    """Persist a shared prompt edit to every step using the same prompt key."""
    if not trace.run_id:
        return PersistOutcome(ok=True)

    affected = [
        record for record in trace.records
        if record.node_uuid and record.prompt_key == prompt_id and record.prompt_path
    ]
    if not affected:
        return PersistOutcome(ok=True)

    failed = []
    for record in affected:
        to_show = _read_to_show(trace.run_id, record.node_uuid)
        if to_show is None:
            failed.append(str(record.index + 1))
            continue
        prompt_path = record.prompt_path or path
        prompt_codec = record.prompt_codec or codec
        if not set_text_value(to_show, prompt_path, prompt_codec, new_text):
            failed.append(str(record.index + 1))
            continue
        if not _post_edit_input(trace.run_id, record.node_uuid, to_show):
            failed.append(str(record.index + 1))

    if failed:
        return PersistOutcome(ok=False, message=f"\n\nFailed to write steps: {', '.join(failed)}.")
    return PersistOutcome(ok=True, message=RERUN_MSG)


def write_input_sections_edit(trace: Trace, turn_index: int, ps: PromptSections) -> PersistOutcome:
    """Persist edited step-local input text blocks to DB for the given turn."""
    if not trace.run_id:
        return PersistOutcome(ok=True)

    record = trace.records[turn_index]
    if not record.node_uuid:
        return PersistOutcome(ok=False, message="\n\nError: step has no DB node reference.")

    to_show = _read_to_show(trace.run_id, record.node_uuid)
    if to_show is None:
        return PersistOutcome(ok=False, message="\n\nError: could not read original input from database.")

    changed = False
    for section in ps.sections:
        if section.shared_prompt:
            continue
        if set_text_value(to_show, section.path, section.codec, section.text):
            changed = True

    if not changed:
        return PersistOutcome(ok=True)
    if not _post_edit_input(trace.run_id, record.node_uuid, to_show):
        return PersistOutcome(ok=False, message="\n\nError: failed to write to database.")
    return PersistOutcome(ok=True, message=RERUN_MSG)
