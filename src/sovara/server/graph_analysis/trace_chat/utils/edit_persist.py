"""Helpers for persisting trace chat edits back to the main server DB.

Calls the main server's /ui/edit-input or /ui/edit-output endpoints so
that DB write, in-memory graph update, and WebSocket broadcast to the UI
all happen through the existing code path.
"""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from .editable_content import EditableContentState
from .trace import Trace
from .text_paths import set_text_value

RERUN_MSG = "\n\nEdit applied and saved."
DISPLAY_ONLY_MSG = "\n\nEdit applied to the displayed trace for this run. Re-run is not available for this edit."


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


def _read_output_to_show(run_id: str, node_uuid: str) -> dict | None:
    """Return the current output to_show dict for a node, or None if unavailable."""
    from sovara.server.database_manager import DB
    row = DB.query_one_llm_call_output(run_id, node_uuid)
    if not row:
        return None
    out = json.loads(dict(row)["output"] or "{}")
    return out.get("to_show")


def _read_graph_to_show(run_id: str, node_uuid: str, branch: str) -> Any | None:
    """Return the current graph-backed to_show payload for a node branch, or None if unavailable."""
    from sovara.server.database_manager import DB
    from sovara.server.graph_models import RunGraph

    row = DB.get_graph(run_id)
    if not row or not row["graph_topology"]:
        return None

    try:
        graph = RunGraph.from_json_string(row["graph_topology"])
    except Exception:
        return None

    node = graph.get_node_by_uuid(node_uuid)
    if node is None:
        return None

    raw_value = node.output if branch == "output" else node.input
    try:
        return json.loads(raw_value or "null")
    except (TypeError, json.JSONDecodeError):
        return None


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


def _post_edit_output(run_id: str, node_uuid: str, to_show: dict) -> bool:
    """Call POST /ui/edit-output on the main server. Returns True on success."""
    from sovara.common.constants import HOST, PORT
    try:
        resp = httpx.post(
            f"http://{HOST}:{PORT}/ui/edit-output",
            json={"run_id": run_id, "node_uuid": node_uuid, "value": json.dumps(to_show)},
            timeout=10.0,
        )
        return resp.is_success
    except Exception:
        return False


def _post_update_node_json(run_id: str, node_uuid: str, branch: str, to_show: Any) -> bool:
    """Call POST /ui/update-node on the main server for graph-only persistence."""
    from sovara.common.constants import HOST, PORT
    try:
        resp = httpx.post(
            f"http://{HOST}:{PORT}/ui/update-node",
            json={
                "run_id": run_id,
                "node_uuid": node_uuid,
                "field": branch,
                "value": json.dumps(to_show),
            },
            timeout=10.0,
        )
        return resp.is_success
    except Exception:
        return False


def write_edit_content(trace: Trace, prompt_id: str, path: str, codec: str, new_text: str) -> PersistOutcome:
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
    used_graph_fallback = False
    for record in affected:
        to_show = _read_to_show(trace.run_id, record.node_uuid)
        use_graph_fallback = False
        if to_show is None:
            to_show = _read_graph_to_show(trace.run_id, record.node_uuid, "input")
            use_graph_fallback = to_show is not None
            used_graph_fallback = used_graph_fallback or use_graph_fallback
        if to_show is None:
            failed.append(str(record.index + 1))
            continue
        prompt_path = record.prompt_path or path
        prompt_codec = record.prompt_codec or codec
        if not set_text_value(to_show, prompt_path, prompt_codec, new_text):
            failed.append(str(record.index + 1))
            continue
        persist_ok = (
            _post_update_node_json(trace.run_id, record.node_uuid, "input", to_show)
            if use_graph_fallback
            else _post_edit_input(trace.run_id, record.node_uuid, to_show)
        )
        if not persist_ok:
            failed.append(str(record.index + 1))

    if failed:
        return PersistOutcome(ok=False, message=f"\n\nFailed to write steps: {', '.join(failed)}.")
    return PersistOutcome(ok=True, message=DISPLAY_ONLY_MSG if used_graph_fallback else RERUN_MSG)


def _write_content_edit(trace: Trace, step_index: int, state: EditableContentState, *, branch: str) -> PersistOutcome:
    """Persist edited step-local content to DB for the given step and branch."""
    if not trace.run_id:
        return PersistOutcome(ok=True)

    record = trace.records[step_index]
    if not record.node_uuid:
        return PersistOutcome(
            ok=False,
            message=f"\n\nError: step has no DB node reference for {branch} edit.",
        )

    if branch == "output":
        to_show = _read_output_to_show(trace.run_id, record.node_uuid)
        post_edit = _post_edit_output
    else:
        to_show = _read_to_show(trace.run_id, record.node_uuid)
        post_edit = _post_edit_input
    used_graph_fallback = False
    if to_show is None:
        to_show = _read_graph_to_show(trace.run_id, record.node_uuid, branch)
        if to_show is not None:
            used_graph_fallback = True
            post_edit = lambda run_id, node_uuid, payload: _post_update_node_json(
                run_id,
                node_uuid,
                branch,
                payload,
            )
    if to_show is None:
        return PersistOutcome(
            ok=False,
            message=f"\n\nError: could not read original {branch} from database or graph.",
        )

    changed = False
    attempted_paths: list[str] = []
    for path_entry in state.paths:
        if path_entry.branch != branch or path_entry.shared_prompt:
            continue
        attempted_paths.append(path_entry.path)
        if set_text_value(to_show, path_entry.path, path_entry.codec, path_entry.text):
            changed = True

    if not attempted_paths:
        return PersistOutcome(ok=True)

    if not changed:
        joined_paths = ", ".join(f"`{path or '<root>'}`" for path in attempted_paths) or "(none)"
        return PersistOutcome(
            ok=False,
            message=f"\n\nError: could not apply edit to {branch} paths: {joined_paths}.",
        )
    if not post_edit(trace.run_id, record.node_uuid, to_show):
        return PersistOutcome(ok=False, message=f"\n\nError: failed to write {branch} to database.")
    return PersistOutcome(ok=True, message=DISPLAY_ONLY_MSG if used_graph_fallback else RERUN_MSG)


def write_input_content_edit(trace: Trace, step_index: int, state: EditableContentState) -> PersistOutcome:
    """Persist edited step-local input content to DB for the given step."""
    return _write_content_edit(trace, step_index, state, branch="input")


def write_output_content_edit(trace: Trace, step_index: int, state: EditableContentState) -> PersistOutcome:
    """Persist edited step-local output content to DB for the given step."""
    return _write_content_edit(trace, step_index, state, branch="output")
