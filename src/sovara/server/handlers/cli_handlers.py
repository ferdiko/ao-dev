"""Helpers backing CLI-oriented UI routes."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from flatten_json import flatten as flatten_complete, unflatten_list

from sovara.runner.monkey_patching.api_parser import json_str_to_api_obj, merge_filtered_into_raw
from sovara.server.database_manager import DB, BadRequestError, ResourceNotFoundError
from sovara.server.graph_models import RunGraph
from sovara.server.handlers.ui_handlers import handle_edit_input, handle_edit_output

if TYPE_CHECKING:
    from sovara.server.state import ServerState


UUID_PREFIX_MIN_LENGTH = 8


def format_timestamp(ts) -> str | None:
    """Format a timestamp to a compact local string."""
    if ts is None:
        return None

    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return ts

    if hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m-%d %H:%M:%S")

    return str(ts)


def _truncate_strings(obj, max_len: int = 20):
    """Recursively truncate string values for preview output."""
    if isinstance(obj, str):
        return obj[:max_len] + "..." if len(obj) > max_len else obj
    if isinstance(obj, dict):
        return {k: _truncate_strings(v, max_len) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_truncate_strings(item, max_len) for item in obj]
    return obj


def _filter_by_key_regex(obj, pattern: str):
    """Filter a JSON-like object by regex over flattened keys."""
    if obj is None:
        return None

    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise BadRequestError(f"Invalid regex pattern: {exc}") from exc

    flattened = flatten_complete(obj, ".")
    filtered = {k: v for k, v in flattened.items() if regex.search(k)}
    return unflatten_list(filtered, ".")


def _effective_input_to_show(llm_call: dict) -> dict | list | str | int | float | bool | None:
    payload = llm_call.get("input_overwrite") or llm_call.get("input")
    if not payload:
        return None

    try:
        parsed = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise BadRequestError(
            f"Stored input payload is invalid for run_id={llm_call['run_id']}, node_uuid={llm_call['node_uuid']}."
        ) from exc

    if not isinstance(parsed, dict):
        raise BadRequestError(
            f"Stored input payload is invalid for run_id={llm_call['run_id']}, node_uuid={llm_call['node_uuid']}."
        )

    return parsed.get("to_show")


def _effective_output_to_show(llm_call: dict) -> dict | list | str | int | float | bool | None:
    payload = llm_call.get("output")
    if not payload:
        return None

    try:
        parsed = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise BadRequestError(
            f"Stored output payload is invalid for run_id={llm_call['run_id']}, node_uuid={llm_call['node_uuid']}."
        ) from exc

    if not isinstance(parsed, dict):
        raise BadRequestError(
            f"Stored output payload is invalid for run_id={llm_call['run_id']}, node_uuid={llm_call['node_uuid']}."
        )

    return parsed.get("to_show")


def _run_status(state: "ServerState | None", run_id: str) -> str:
    if state is None:
        return "finished"
    run_map, _running_ids = state.get_run_snapshot()
    run = run_map.get(run_id)
    return run.status if run else "finished"


def _is_empty_probe_payload(value: Any) -> bool:
    """Return True when a filtered probe payload has no visible matches."""
    return value is None or value == {} or value == []


def _normalize_uuid_prefix(value: str, *, label: str) -> str:
    compact = value.strip().lower().replace("-", "")
    if not compact:
        raise BadRequestError(f"{label} must not be empty.")
    if len(compact) < UUID_PREFIX_MIN_LENGTH:
        raise BadRequestError(
            f"{label} prefix must be at least {UUID_PREFIX_MIN_LENGTH} hex characters."
        )
    if len(compact) > 32 or not re.fullmatch(r"[0-9a-f]+", compact):
        raise BadRequestError(
            f"{label} must be a UUID or UUID prefix containing only hex characters and optional hyphens."
        )
    return compact


def _resolve_uuid_prefix(value: str, candidates: list[str], *, label: str) -> str:
    normalized = _normalize_uuid_prefix(value, label=label)
    exact_matches = [
        candidate
        for candidate in candidates
        if candidate.lower().replace("-", "") == normalized
    ]
    if exact_matches:
        return exact_matches[0]

    matches = [
        candidate
        for candidate in candidates
        if candidate.lower().replace("-", "").startswith(normalized)
    ]
    if not matches:
        raise ResourceNotFoundError(f"{label} not found: {value}")
    if len(matches) > 1:
        joined = ", ".join(sorted(matches))
        raise BadRequestError(
            f"Ambiguous {label} prefix '{value}'. Matches: {joined}. Provide a longer prefix."
        )
    return matches[0]


def _resolve_run_id(value: str) -> str:
    candidates = DB.find_run_ids_by_prefix(_normalize_uuid_prefix(value, label="Run ID"))
    return _resolve_uuid_prefix(value, candidates, label="Run ID")


def _resolve_node_uuid(run_id: str, value: str) -> str:
    candidates = DB.find_node_uuids_by_prefix(run_id, _normalize_uuid_prefix(value, label="Node UUID"))
    return _resolve_uuid_prefix(value, candidates, label="Node UUID")


def build_probe_response(
    run_id: str,
    *,
    state: "ServerState | None" = None,
    node_uuid: str | None = None,
    node_uuids: list[str] | None = None,
    preview: bool = False,
    show_input: bool = False,
    show_output: bool = False,
    key_regex: str | None = None,
) -> dict:
    """Return the probe payload previously built inside so-cli."""
    resolved_run_id = _resolve_run_id(run_id)
    run = DB.get_run_metadata(resolved_run_id)
    if not run:
        raise ResourceNotFoundError(f"Run not found: {run_id}")

    graph = RunGraph.from_json_string(run["graph_topology"])
    parent_ids: dict[str, list[str]] = {}
    child_ids: dict[str, list[str]] = {}
    for edge in graph.edges:
        parent_ids.setdefault(edge.target_uuid, []).append(edge.source_uuid)
        child_ids.setdefault(edge.source_uuid, []).append(edge.target_uuid)

    if node_uuid or node_uuids:
        requested = [node_uuid] if node_uuid else node_uuids or []
        nodes_data = []
        include_input = not show_output or show_input
        include_output = not show_input or show_output

        for raw_node_uuid in requested:
            current_node_uuid = _resolve_node_uuid(resolved_run_id, raw_node_uuid.strip())
            row = DB.get_llm_call_full(resolved_run_id, current_node_uuid)
            if not row:
                raise ResourceNotFoundError(f"Node not found: {current_node_uuid}")

            llm_call = dict(row)
            llm_call["run_id"] = resolved_run_id

            input_to_show = _effective_input_to_show(llm_call)
            output_to_show = _effective_output_to_show(llm_call)

            if key_regex:
                input_to_show = _filter_by_key_regex(input_to_show, key_regex)
                output_to_show = _filter_by_key_regex(output_to_show, key_regex)

            if preview:
                input_to_show = _truncate_strings(input_to_show)
                output_to_show = _truncate_strings(output_to_show)

            if isinstance(input_to_show, dict):
                input_to_show = flatten_complete(input_to_show, ".")
            if isinstance(output_to_show, dict):
                output_to_show = flatten_complete(output_to_show, ".")

            stack_trace = llm_call.get("stack_trace")
            if stack_trace:
                stack_trace = [line.strip() for line in stack_trace.split("\n") if line.strip()]

            node_info = {
                "node_uuid": current_node_uuid,
                "run_id": resolved_run_id,
                "api_type": llm_call["api_type"],
                "node_kind": llm_call.get("node_kind"),
                "label": llm_call["label"],
                "timestamp": format_timestamp(llm_call["timestamp"]),
                "parent_uuids": parent_ids.get(current_node_uuid, []),
                "child_uuids": child_ids.get(current_node_uuid, []),
                "has_input_overwrite": llm_call["input_overwrite"] is not None,
                "stack_trace": stack_trace,
            }

            if include_input:
                node_info["input"] = input_to_show
            if include_output:
                node_info["output"] = output_to_show
            if key_regex and (
                (include_input and _is_empty_probe_payload(input_to_show))
                and (include_output and _is_empty_probe_payload(output_to_show))
                or (include_input and not include_output and _is_empty_probe_payload(input_to_show))
                or (include_output and not include_input and _is_empty_probe_payload(output_to_show))
            ):
                node_info["hint"] = (
                    "No keys matched --key-regex in the selected fields. "
                    "Re-run probe with --preview on this node to inspect available flattened keys."
                )

            nodes_data.append(node_info)

        if node_uuid:
            return nodes_data[0]
        return {"nodes": nodes_data}

    return {
        "run_id": resolved_run_id,
        "name": run["name"],
        "status": _run_status(state, resolved_run_id),
        "timestamp": format_timestamp(run["timestamp"]),
        "custom_metrics": DB._parse_custom_metrics(run["custom_metrics"]),
        "thumb_label": DB._normalize_thumb_label(run["thumb_label"]),
        "version_date": run["version_date"],
        "node_count": len(graph.nodes),
        "nodes": [
            {
                "node_uuid": node.uuid,
                "step_id": node.step_id,
                "label": node.label,
                "parent_uuids": parent_ids.get(node.uuid, []),
                "child_uuids": child_ids.get(node.uuid, []),
            }
            for node in graph.nodes
        ],
        "edges": [
            {"source_uuid": edge.source_uuid, "target_uuid": edge.target_uuid}
            for edge in graph.edges
        ],
    }


def build_key_edit_value(run_id: str, node_uuid: str, field: str, key: str, value: str) -> str:
    """Build a nested ``to_show`` JSON payload for a single flattened-key edit."""
    if field not in {"input", "output"}:
        raise BadRequestError("field must be 'input' or 'output'.")

    row = DB.get_llm_call_full(run_id, node_uuid)
    if not row:
        raise ResourceNotFoundError(f"Node {node_uuid} not found in run {run_id}")

    llm_call = dict(row)
    llm_call["run_id"] = run_id

    if field == "input":
        payload = llm_call.get("input_overwrite") or llm_call.get("input")
        missing_message = f"Input node not found for run_id={run_id}, node_uuid={node_uuid}."
    else:
        payload = llm_call.get("output")
        missing_message = f"Output node not found for run_id={run_id}, node_uuid={node_uuid}."

    if not payload:
        raise ResourceNotFoundError(missing_message)

    try:
        current_data = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise BadRequestError(
            f"Stored {field} payload is invalid for run_id={run_id}, node_uuid={node_uuid}."
        ) from exc

    if not isinstance(current_data, dict) or "raw" not in current_data or "to_show" not in current_data:
        raise BadRequestError(
            f"Stored {field} payload is incomplete for run_id={run_id}, node_uuid={node_uuid}."
        )

    to_show = current_data["to_show"]
    if not isinstance(to_show, dict):
        raise BadRequestError(
            f"Stored {field} payload is not key-addressable for run_id={run_id}, node_uuid={node_uuid}."
        )

    flat_to_show = flatten_complete(to_show, ".")
    if key not in flat_to_show:
        raise BadRequestError(f"Key '{key}' not found. Available keys: {sorted(flat_to_show.keys())}")

    try:
        parsed_value = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        parsed_value = value

    flat_to_show[key] = parsed_value
    new_to_show = unflatten_list(flat_to_show, ".")

    try:
        merged_raw = merge_filtered_into_raw(current_data["raw"], new_to_show)
    except Exception as exc:
        raise BadRequestError(f"Failed to merge edit: {exc}") from exc

    if field == "output":
        overwrite = json.dumps({"raw": merged_raw, "to_show": new_to_show}, sort_keys=True)
        try:
            json_str_to_api_obj(overwrite, llm_call["api_type"])
        except Exception as exc:
            raise BadRequestError(f"Validation failed: {exc}") from exc

    return json.dumps(new_to_show, sort_keys=True)


def prepare_edit_rerun(
    state: "ServerState",
    source_run_id: str,
    *,
    node_uuid: str,
    field: str,
    key: str,
    value: str,
    run_name: str | None = None,
) -> dict:
    """Clone a run, apply one key edit, and return the spawn context for the CLI."""
    resolved_source_run_id = _resolve_run_id(source_run_id)
    run = DB.get_run_metadata(resolved_source_run_id)
    if not run:
        raise ResourceNotFoundError(f"Run not found: {source_run_id}")

    resolved_node_uuid = _resolve_node_uuid(resolved_source_run_id, node_uuid)

    cwd, command, environment = DB.get_exec_command(resolved_source_run_id)
    if not command:
        raise BadRequestError(f"No command stored for run: {resolved_source_run_id}")

    run_context = DB.query_one(
        "SELECT project_id, user_id FROM runs WHERE run_id=?",
        (resolved_source_run_id,),
    )

    new_run_id = str(uuid.uuid4())
    if run_name is None:
        base_name = run["name"] or resolved_source_run_id
        run_name = f"Edit of {base_name}"

    DB.add_run(
        run_id=new_run_id,
        name=run_name,
        timestamp=datetime.now(timezone.utc),
        cwd=cwd,
        command=command,
        environment=environment,
        parent_run_id=new_run_id,
        version_date=run["version_date"],
        project_id=run_context["project_id"] if run_context else None,
        user_id=run_context["user_id"] if run_context else None,
    )

    if run["graph_topology"]:
        DB.update_graph_topology(new_run_id, RunGraph.from_json_string(run["graph_topology"]))

    DB.copy_llm_calls(resolved_source_run_id, new_run_id)
    DB.copy_prior_retrievals(resolved_source_run_id, new_run_id)

    new_value = build_key_edit_value(new_run_id, resolved_node_uuid, field, key, value)
    message = {"run_id": new_run_id, "node_uuid": resolved_node_uuid, "value": new_value}
    if field == "input":
        handle_edit_input(state, message)
    else:
        handle_edit_output(state, message)

    return {
        "run_id": new_run_id,
        "node_uuid": resolved_node_uuid,
        "edited_field": field,
        "edited_key": key,
        "cwd": cwd,
        "command": command,
        "environment": environment,
    }
