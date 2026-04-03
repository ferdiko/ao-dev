"""Helpers for persisting trace chat edits back to the main server DB."""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from .trace import Trace

RERUN_MSG = "\n\nEdit applied and saved."
DISPLAY_ONLY_MSG = "\n\nEdit applied to the displayed trace for this run. Re-run is not available for this edit."


@dataclass
class PersistOutcome:
    ok: bool
    message: str = ""


def _read_to_show(run_id: str, node_uuid: str) -> dict | None:
    """Return the current to_show dict for a node, or None if unavailable."""
    from sovara.server.database import DB
    row = DB.query_one_llm_call_input(run_id, node_uuid)
    if not row:
        return None
    inp = json.loads(dict(row)["input"] or "{}")
    return inp.get("to_show")


def _read_output_to_show(run_id: str, node_uuid: str) -> dict | None:
    """Return the current output to_show dict for a node, or None if unavailable."""
    from sovara.server.database import DB
    row = DB.query_one_llm_call_output(run_id, node_uuid)
    if not row:
        return None
    out = json.loads(dict(row)["output"] or "{}")
    return out.get("to_show")


def _read_graph_to_show(run_id: str, node_uuid: str, branch: str) -> Any | None:
    """Return the current graph-backed to_show payload for a node branch, or None if unavailable."""
    from sovara.server.database import DB
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


def _write_branch_to_show(
    trace: Trace,
    step_index: int,
    to_show: dict,
    *,
    branch: str,
) -> PersistOutcome:
    if not trace.run_id:
        return PersistOutcome(ok=True)

    record = trace.records[step_index]
    if not record.node_uuid:
        return PersistOutcome(
            ok=False,
            message=f"\n\nError: step has no DB node reference for {branch} edit.",
        )

    if branch == "output":
        current = _read_output_to_show(trace.run_id, record.node_uuid)
        post_edit = _post_edit_output
    else:
        current = _read_to_show(trace.run_id, record.node_uuid)
        post_edit = _post_edit_input

    if current is not None:
        if not post_edit(trace.run_id, record.node_uuid, to_show):
            return PersistOutcome(ok=False, message=f"\n\nError: failed to write {branch} to database.")
        return PersistOutcome(ok=True, message=RERUN_MSG)

    if _read_graph_to_show(trace.run_id, record.node_uuid, branch) is None:
        return PersistOutcome(
            ok=False,
            message=f"\n\nError: could not read original {branch} from database or graph.",
        )

    if not _post_update_node_json(trace.run_id, record.node_uuid, branch, to_show):
        return PersistOutcome(ok=False, message=f"\n\nError: failed to write {branch} to database.")
    return PersistOutcome(ok=True, message=DISPLAY_ONLY_MSG)


def write_input_content_edit(trace: Trace, step_index: int, to_show: dict) -> PersistOutcome:
    """Persist edited step-local input content to DB for the given step."""
    return _write_branch_to_show(trace, step_index, to_show, branch="input")


def write_output_content_edit(trace: Trace, step_index: int, to_show: dict) -> PersistOutcome:
    """Persist edited step-local output content to DB for the given step."""
    return _write_branch_to_show(trace, step_index, to_show, branch="output")
