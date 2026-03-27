"""Helpers for persisting trace chat edits back to the main server DB.

Calls the main server's /ui/edit-input endpoint so that DB write,
in-memory graph update, and WebSocket broadcast to the UI all happen
through the existing code path.
"""

import json

import httpx

from .trace import Trace, _prompt_hash

RERUN_MSG = "\n\nEdit applied and saved."


def _read_to_show(session_id: str, node_uuid: str) -> dict | None:
    """Return the current to_show dict for a node, or None if unavailable."""
    from sovara.server.database_manager import DB
    row = DB.query_one_llm_call_input(session_id, node_uuid)
    if not row:
        return None
    inp = json.loads(dict(row)["input"] or "{}")
    return inp.get("to_show")


def _post_edit_input(session_id: str, node_uuid: str, to_show: dict) -> bool:
    """Call POST /ui/edit-input on the main server. Returns True on success."""
    from sovara.common.constants import HOST, PORT
    try:
        resp = httpx.post(
            f"http://{HOST}:{PORT}/ui/edit-input",
            json={"session_id": session_id, "node_uuid": node_uuid, "value": json.dumps(to_show)},
            timeout=10.0,
        )
        return resp.is_success
    except Exception:
        return False


def write_prompt_edit(trace: Trace, prompt_id: str) -> str:
    """Persist the edited system prompt to DB for all turns sharing this prompt.

    Finds every record with the matching prompt_id, reads its current to_show,
    replaces the system prompt field, and calls /ui/edit-input for each.
    Handles both Anthropic format (body.system) and OpenAI format (role=system
    message in body.messages).
    """
    if not trace.session_id:
        return ""  # Not built from DB; skip silently (e.g. CLI usage)

    new_prompt = trace.prompt_registry[prompt_id]
    affected = [r for r in trace.records
                if r.node_uuid and r.system_prompt and _prompt_hash(r.system_prompt) == prompt_id]
    if not affected:
        return ""  # No DB nodes found; not an error (e.g. trace loaded from file)

    failed = []
    for r in affected:
        to_show = _read_to_show(trace.session_id, r.node_uuid)
        if to_show is None:
            failed.append(str(r.index))
            continue
        if "body.system" in to_show:
            to_show["body.system"] = new_prompt
        else:
            for m in to_show.get("body.messages", []):
                if m.get("role") == "system":
                    m["content"] = new_prompt
                    break
        if not _post_edit_input(trace.session_id, r.node_uuid, to_show):
            failed.append(str(r.index))

    if failed:
        return f"\n\nFailed to write steps: {', '.join(failed)}."
    return RERUN_MSG


def _replace_content(msg: dict, new_text: str) -> None:
    """Replace a message's text content, preserving format (string vs Anthropic blocks)."""
    content = msg["content"]
    if isinstance(content, list):
        non_text = [b for b in content if not (isinstance(b, dict) and b.get("type") == "text")]
        msg["content"] = non_text + [{"type": "text", "text": new_text}]
    else:
        msg["content"] = new_text


def write_input_sections_edit(trace: Trace, turn_index: int) -> str:
    """Persist edited input message sections to DB for the given turn.

    Groups sections by msg_index, reassembles each message's content,
    and splices edited messages back into to_show["body.messages"].
    """
    if not trace.session_id:
        return ""

    from collections import defaultdict

    ps = trace.prompt_sections_cache[f"step:{turn_index}"]
    original_msgs = trace.diffed[turn_index].new_messages

    # Group message sections (msg_index >= 0) by their source message
    groups: dict[int, list] = defaultdict(list)
    for s in ps.sections:
        if s.msg_index >= 0:
            groups[s.msg_index].append(s)

    edited_msgs = []
    for i, msg in enumerate(original_msgs):
        new_msg = dict(msg)
        if i in groups:
            _replace_content(new_msg, "\n\n".join(s.text for s in groups[i]))
        edited_msgs.append(new_msg)

    record = trace.records[turn_index]
    if not record.node_uuid:
        return "\n\nError: step has no DB node reference."

    to_show = _read_to_show(trace.session_id, record.node_uuid)
    if to_show is None:
        return "\n\nError: could not read original input from database."

    # New messages are always the tail of body.messages
    messages = to_show["body.messages"]
    messages[-len(original_msgs):] = edited_msgs

    if not _post_edit_input(trace.session_id, record.node_uuid, to_show):
        return "\n\nError: failed to write to database."
    return RERUN_MSG
