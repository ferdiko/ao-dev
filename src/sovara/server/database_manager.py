"""
Database manager for experiment and LLM call data.

This module provides a unified interface for database operations using SQLite.
"""

import time
import uuid
import json
import random
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Any

from sovara.common.custom_metrics import MetricColumn, get_metric_kind
from sovara.common.logger import logger

from sovara.runner.monkey_patching.api_parser import (
    func_kwargs_to_json_str,
    json_str_to_api_obj,
    api_obj_to_json_str,
    json_str_to_original_inp_dict,
    api_obj_to_response_ok,
    merge_filtered_into_raw,
)
from sovara.server.graph_models import SessionGraph


class ResourceNotFoundError(LookupError):
    """Raised when a request references a missing DB-backed resource."""


class BadRequestError(ValueError):
    """Raised when a request payload cannot be applied safely."""


@dataclass
class CacheOutput:
    """
    Encapsulates the output of cache operations for LLM calls.

    This dataclass stores all the necessary information returned by cache lookups
    and used for cache storage operations.

    Attributes:
        input_dict: The (potentially modified) input dictionary for the LLM call
        output: The cached output object, None if not cached or cache miss
        node_uuid: Unique identifier for this LLM call node, None if new call
        input_pickle: Serialized input data for caching purposes
        input_hash: Hash of the input for efficient cache lookups
        session_id: The session ID associated with this cache operation
        stack_trace: Python stack trace at the point of the LLM call
    """

    input_dict: dict
    output: Optional[Any]
    node_uuid: Optional[str]
    input_pickle: bytes
    input_hash: str
    session_id: str
    stack_trace: Optional[str] = None


class DatabaseManager:
    """Manages database operations using SQLite backend."""

    def __init__(self):
        from sovara.common.constants import ATTACHMENT_CACHE

        self.cache_attachments = True
        self.attachment_cache_dir = ATTACHMENT_CACHE
        # Tracks per-(session_id, input_hash) lookup count so concurrent
        # identical calls (e.g. ensemble candidates) each get a distinct
        # cached row instead of all hitting the same first row.
        self._occurrence_counters: dict[tuple[str, str], int] = defaultdict(int)
        self._occurrence_lock = threading.Lock()

    @property
    def user_id(self):
        from sovara.common.user import read_user_id
        return read_user_id()

    def _next_occurrence(self, session_id: str, input_hash: str) -> int:
        """Return and increment the lookup count for (session_id, input_hash)."""
        with self._occurrence_lock:
            key = (session_id, input_hash)
            occurrence = self._occurrence_counters[key]
            self._occurrence_counters[key] += 1
            return occurrence

    @property
    def backend(self):
        """Return the SQLite backend module (lazy-loaded)."""
        if not hasattr(self, "_backend_module"):
            from sovara.server.database_backends import sqlite

            self._backend_module = sqlite
        return self._backend_module

    # Low-level database operations
    def query_one(self, query, params=None):
        return self.backend.query_one(query, params or ())

    def query_all(self, query, params=None):
        return self.backend.query_all(query, params or ())

    def execute(self, query, params=None):
        return self.backend.execute(query, params or ())

    def clear_connections(self) -> None:
        """Release any backend-managed connections/resources for the current process."""
        clear = getattr(self.backend, "clear_connections", None)
        if callable(clear):
            clear()

    def set_input_overwrite(self, session_id, node_uuid, new_input):
        """UI sends to_show data; merge into original raw to build full format for the runner.
        Returns the full-format overwrite string, or None if unchanged."""
        try:
            new_to_show = json.loads(new_input)
        except json.JSONDecodeError as exc:
            raise BadRequestError(
                f"Invalid input JSON for session_id={session_id}, node_uuid={node_uuid}: {exc.msg}."
            ) from exc

        row = self.backend.get_llm_call_input_api_type_query(session_id, node_uuid)
        if not row:
            raise ResourceNotFoundError(
                f"Input node not found for session_id={session_id}, node_uuid={node_uuid}."
            )

        try:
            original = json.loads(row["input"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise BadRequestError(
                f"Stored input payload is invalid for session_id={session_id}, node_uuid={node_uuid}."
            ) from exc

        if not isinstance(original, dict) or "raw" not in original or "to_show" not in original:
            raise BadRequestError(
                f"Stored input payload is incomplete for session_id={session_id}, node_uuid={node_uuid}."
            )

        if json.dumps(new_to_show, sort_keys=True) == json.dumps(original["to_show"], sort_keys=True):
            return None

        merged_raw = merge_filtered_into_raw(original["raw"], new_to_show)
        overwrite = json.dumps({"raw": merged_raw, "to_show": new_to_show}, sort_keys=True)
        self.backend.set_input_overwrite_query(overwrite, session_id, node_uuid)
        return overwrite

    def set_output_overwrite(self, session_id, node_uuid, new_output: str):
        """UI sends to_show data; merge into original raw to build full format for the runner.
        Returns the full-format overwrite string, or None if unchanged or error."""
        try:
            new_to_show = json.loads(new_output)
        except json.JSONDecodeError as exc:
            raise BadRequestError(
                f"Invalid output JSON for session_id={session_id}, node_uuid={node_uuid}: {exc.msg}."
            ) from exc

        row = self.backend.get_llm_call_output_api_type_query(session_id, node_uuid)

        if not row:
            raise ResourceNotFoundError(
                f"Output node not found for session_id={session_id}, node_uuid={node_uuid}."
            )

        if row["output"] is None:
            raise BadRequestError(
                f"No stored output is available for session_id={session_id}, node_uuid={node_uuid}."
            )

        try:
            original = json.loads(row["output"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise BadRequestError(
                f"Stored output payload is invalid for session_id={session_id}, node_uuid={node_uuid}."
            ) from exc

        if not isinstance(original, dict) or "raw" not in original or "to_show" not in original:
            raise BadRequestError(
                f"Stored output payload is incomplete for session_id={session_id}, node_uuid={node_uuid}."
            )

        try:
            merged_raw = merge_filtered_into_raw(original["raw"], new_to_show)
            overwrite = json.dumps({"raw": merged_raw, "to_show": new_to_show}, sort_keys=True)

            json_str_to_api_obj(overwrite, row["api_type"])
            self.backend.set_output_overwrite_query(overwrite, session_id, node_uuid)
            return overwrite
        except Exception as e:
            raise BadRequestError(
                f"Invalid output edit for session_id={session_id}, node_uuid={node_uuid}: {e}"
            ) from e

    def erase(self, session_id):
        """Erase experiment data."""
        default_graph = json.dumps({"nodes": [], "edges": []})
        self.backend.delete_llm_calls_query(session_id)
        self.backend.update_experiment_graph_topology_query(default_graph, session_id)

    def get_user(self, user_id):
        return self.backend.get_user_query(user_id)

    def upsert_user(self, user_id, full_name, email):
        self.backend.upsert_user_query(user_id, full_name, email)

    def add_experiment(
        self,
        session_id,
        name,
        timestamp,
        cwd,
        command,
        environment,
        parent_session_id=None,
        version_date=None,
        project_id=None,
        user_id=None,
    ):
        """Add experiment to database."""
        from sovara.common.constants import DEFAULT_LOG, DEFAULT_NOTE

        default_graph = json.dumps({"nodes": [], "edges": []})
        parent_session_id = parent_session_id if parent_session_id else session_id
        env_json = json.dumps(environment)
        serialized_timestamp = self._serialize_timestamp(timestamp)

        self.backend.add_experiment_query(
            session_id,
            parent_session_id,
            name,
            default_graph,
            serialized_timestamp,
            cwd,
            command,
            env_json,
            DEFAULT_NOTE,
            DEFAULT_LOG,
            version_date,
            project_id,
            user_id,
        )

    def update_graph_topology(self, session_id: str, graph: SessionGraph) -> None:
        graph_json = graph.to_json_string()
        self.backend.update_experiment_graph_topology_query(graph_json, session_id)

    def update_timestamp(self, session_id, timestamp):
        self.backend.update_experiment_timestamp_query(self._serialize_timestamp(timestamp), session_id)

    def update_runtime_seconds(self, session_id, runtime_seconds):
        normalized = self._normalize_runtime_seconds(runtime_seconds)
        self.backend.update_experiment_runtime_seconds_query(normalized, session_id)

    def update_active_runtime_seconds(self, session_id, active_runtime_seconds):
        normalized = self._normalize_runtime_seconds(active_runtime_seconds)
        self.backend.update_experiment_active_runtime_seconds_query(normalized, session_id)

    def clear_active_runtime_seconds(self, session_id):
        self.backend.clear_experiment_active_runtime_seconds_query(session_id)

    def checkpoint_active_runtime(self, session_id, active_runtime_seconds=None):
        if active_runtime_seconds is None:
            from sovara.runner.context_manager import get_session_runtime_seconds

            active_runtime_seconds = get_session_runtime_seconds(session_id)
        if active_runtime_seconds is None:
            return None
        normalized = self._normalize_runtime_seconds(active_runtime_seconds)
        self.backend.update_experiment_active_runtime_seconds_query(normalized, session_id)
        return normalized

    def finalize_runtime(self, session_id, runtime_seconds):
        normalized = self._normalize_runtime_seconds(runtime_seconds)
        self.backend.finalize_experiment_runtime_query(normalized, session_id)
        return normalized

    def update_run_name(self, session_id, run_name):
        self.backend.update_experiment_name_query(run_name, session_id)

    def update_thumb_label(self, session_id, thumb_label):
        self.backend.update_experiment_thumb_label_query(thumb_label, session_id)

    @staticmethod
    def _normalize_tag_row(row):
        return {
            "tag_id": row["tag_id"],
            "name": row["name"],
            "color": row["color"],
        }

    def get_project_tags(self, project_id):
        rows = self.backend.get_project_tags_query(project_id)
        return [self._normalize_tag_row(row) for row in rows]

    def create_project_tag(self, project_id, name, color):
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found.")

        normalized_name = str(name).strip()
        if not normalized_name:
            raise ValueError("Tag name is required.")

        if self.backend.get_project_tag_by_name_query(project_id, normalized_name):
            raise ValueError("A tag with this name already exists in the project.")

        tag_id = str(uuid.uuid4())
        self.backend.insert_project_tag_query(tag_id, project_id, normalized_name, color)
        return self._normalize_tag_row(self.backend.get_project_tag_query(tag_id))

    def delete_project_tag(self, project_id, tag_id):
        row = self.backend.get_project_tag_query(tag_id)
        if row is None or row["project_id"] != project_id:
            raise ValueError("Tag not found.")
        self.backend.delete_project_tag_query(project_id, tag_id)

    def replace_run_tags(self, session_id, tag_ids):
        context = self.backend.get_experiment_tag_context_query(session_id)
        if context is None:
            raise ValueError("Run not found.")

        project_id = context["project_id"]
        if not project_id:
            raise ValueError("Tags can only be assigned to project-scoped runs.")

        unique_tag_ids = list(dict.fromkeys(tag_ids))
        if unique_tag_ids:
            project_tags = self.backend.get_project_tags_by_ids_query(project_id, unique_tag_ids)
            if len(project_tags) != len(unique_tag_ids):
                raise ValueError("All tags must belong to the run's project.")

        self.backend.replace_experiment_tags_query(session_id, unique_tag_ids)
        return self._get_tags_for_sessions_map([session_id]).get(session_id, [])

    def update_notes(self, session_id, notes):
        self.backend.update_experiment_notes_query(notes, session_id)

    def update_command(self, session_id, command):
        self.backend.update_experiment_command_query(command, session_id)

    def update_experiment_version_date(self, session_id, version_date):
        self.backend.update_experiment_version_date_query(
            self._serialize_timestamp(version_date),
            session_id,
        )

    def add_metrics(self, session_id, metrics):
        """Persist validated custom metrics for a run."""
        row = self.backend.get_experiment_metrics_context_query(session_id)
        if row is None:
            raise ValueError(f"Unknown session_id: {session_id}")

        existing_metrics = self._parse_custom_metrics(row["custom_metrics"])
        repeated_keys = sorted(set(existing_metrics) & set(metrics))
        if repeated_keys:
            repeated = ", ".join(repeated_keys)
            raise ValueError(f"Metrics already logged for this run: {repeated}")

        project_id = row["project_id"]
        if project_id:
            existing_kinds = {
                item["metric_key"]: item["metric_kind"]
                for item in self.backend.get_project_metric_kinds_query(project_id)
            }
            for key, value in metrics.items():
                kind = get_metric_kind(value)
                existing_kind = existing_kinds.get(key)
                if existing_kind and existing_kind != kind:
                    raise ValueError(
                        f"Metric '{key}' is already registered as kind '{existing_kind}' for this project."
                    )
            for key, value in metrics.items():
                if key not in existing_kinds:
                    self.backend.upsert_project_metric_kind_query(project_id, key, get_metric_kind(value))

        updated_metrics = {**existing_metrics, **metrics}
        self.backend.update_experiment_custom_metrics_query(
            json.dumps(updated_metrics, sort_keys=True),
            session_id,
        )
        return updated_metrics

    @staticmethod
    def _parse_custom_metrics(raw_metrics):
        if isinstance(raw_metrics, dict):
            return raw_metrics
        if not raw_metrics:
            return {}
        try:
            parsed = json.loads(raw_metrics)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _serialize_timestamp(timestamp):
        if timestamp is None or isinstance(timestamp, str):
            return timestamp
        if isinstance(timestamp, datetime):
            # Store timestamps as naive UTC strings so lexical ordering still
            # works in SQLite and the UI can consistently parse them as UTC.
            if timestamp.tzinfo is not None:
                timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
            return timestamp.strftime("%Y-%m-%d %H:%M:%S")
        raise TypeError(f"Unsupported timestamp type: {type(timestamp)!r}")

    @staticmethod
    def _normalize_thumb_label(raw_value):
        if raw_value is None:
            return None
        return bool(raw_value)

    @staticmethod
    def _normalize_runtime_seconds(raw_value):
        if raw_value is None:
            return None
        return max(0.0, float(raw_value))

    def _normalize_experiment_row(self, row):
        normalized = dict(row)
        normalized["custom_metrics"] = self._parse_custom_metrics(normalized.get("custom_metrics"))
        normalized["thumb_label"] = self._normalize_thumb_label(normalized.get("thumb_label"))
        normalized["runtime_seconds"] = self._normalize_runtime_seconds(normalized.get("runtime_seconds"))
        normalized["active_runtime_seconds"] = self._normalize_runtime_seconds(normalized.get("active_runtime_seconds"))
        normalized["tags"] = list(normalized.get("tags") or [])
        return normalized

    def _get_tags_for_sessions_map(self, session_ids):
        rows = self.backend.get_tags_for_sessions_query(session_ids)
        tags_by_session: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            tags_by_session[row["session_id"]].append(self._normalize_tag_row(row))
        return tags_by_session

    def _attach_tags_to_rows(self, rows):
        normalized_rows = [self._normalize_experiment_row(row) for row in rows]
        session_ids = [row["session_id"] for row in normalized_rows]
        tags_by_session = self._get_tags_for_sessions_map(session_ids)
        for row in normalized_rows:
            row["tags"] = tags_by_session.get(row["session_id"], [])
        return normalized_rows

    @staticmethod
    def _get_runtime_sort_value(row):
        return row["runtime_seconds"] if row["runtime_seconds"] is not None else row["active_runtime_seconds"]

    def _matches_custom_metric_filters(self, row, metric_filters):
        metrics = row["custom_metrics"]
        for key, filter_def in metric_filters.items():
            if key not in metrics:
                return False
            value = metrics[key]
            if filter_def["kind"] == "bool":
                if value not in filter_def["values"]:
                    return False
                continue
            if isinstance(value, bool):
                return False
            min_value = filter_def.get("min")
            max_value = filter_def.get("max")
            if min_value is not None and value < min_value:
                return False
            if max_value is not None and value > max_value:
                return False
        return True

    def _matches_label_filters(self, row, labels):
        if not labels:
            return True
        thumb_label = row["thumb_label"]
        token = "none" if thumb_label is None else "up" if thumb_label else "down"
        return token in labels

    def _matches_tag_filters(self, row, tag_ids):
        if not tag_ids:
            return True
        assigned_ids = {tag["tag_id"] for tag in row["tags"]}
        return set(tag_ids).issubset(assigned_ids)

    def _build_custom_metric_columns(self, rows):
        values_by_key: dict[str, list[bool | int | float]] = defaultdict(list)
        for row in rows:
            for key, value in row["custom_metrics"].items():
                values_by_key[key].append(value)

        columns = []
        for key in sorted(values_by_key):
            values = values_by_key[key]
            kinds = {get_metric_kind(value) for value in values}
            if len(kinds) != 1:
                raise ValueError(f"Metric '{key}' has inconsistent kinds in the filtered result set.")
            kind = kinds.pop()
            if kind == "bool":
                column = MetricColumn(key=key, kind=kind, values=sorted(set(values)))
            elif kind == "int":
                ints = [int(value) for value in values]
                column = MetricColumn(key=key, kind=kind, min=min(ints), max=max(ints))
            else:
                floats = [float(value) for value in values]
                column = MetricColumn(key=key, kind=kind, min=min(floats), max=max(floats))
            columns.append(column.model_dump())
        return columns

    def _sort_experiment_rows(self, rows, sort_key, sort_dir):
        reverse = sort_dir.lower() == "desc"

        if sort_key.startswith("metric:"):
            metric_key = sort_key.split(":", 1)[1]
            present = [row for row in rows if metric_key in row["custom_metrics"]]
            missing = [row for row in rows if metric_key not in row["custom_metrics"]]
            present.sort(key=lambda row: row["custom_metrics"][metric_key], reverse=reverse)
            return present + missing

        if sort_key == "label":
            rank = {None: -1, False: 0, True: 1}
            return sorted(rows, key=lambda row: rank[row["thumb_label"]], reverse=reverse)

        if sort_key == "latency":
            present = [row for row in rows if self._get_runtime_sort_value(row) is not None]
            missing = [row for row in rows if self._get_runtime_sort_value(row) is None]
            present.sort(key=self._get_runtime_sort_value, reverse=reverse)
            return present + missing

        if sort_key == "tags":
            return sorted(
                rows,
                key=lambda row: ",".join(tag["name"].lower() for tag in row["tags"]),
                reverse=reverse,
            )

        sort_field = {
            "timestamp": "timestamp",
            "sessionId": "session_id",
            "name": "name",
            "codeVersion": "version_date",
        }.get(sort_key, "timestamp")
        return sorted(
            rows,
            key=lambda row: (
                row.get(sort_field) is None,
                row.get(sort_field) or "",
            ),
            reverse=reverse,
        )

    def get_experiment_table_view(self, project_id, exclude_ids, filters, sort_key, sort_dir, limit, offset):
        base_filters = {
            "name": filters.get("name"),
            "session_id": filters.get("session_id"),
            "version_date": filters.get("version_date"),
            "timestamp_from": filters.get("timestamp_from"),
            "timestamp_to": filters.get("timestamp_to"),
        }
        rows, _ = self.backend.query_experiments_filtered(
            project_id,
            exclude_ids,
            base_filters,
            "timestamp",
            "DESC",
            None,
            0,
            user_id=self.user_id,
        )
        normalized_rows = self._attach_tags_to_rows(rows)
        filtered_rows = [
            row
            for row in normalized_rows
            if self._matches_label_filters(row, filters.get("thumb_label", []))
            and self._matches_tag_filters(row, filters.get("tag_ids", []))
            and self._matches_custom_metric_filters(row, filters.get("custom_metrics", {}))
        ]
        custom_metric_columns = self._build_custom_metric_columns(filtered_rows)
        sorted_rows = self._sort_experiment_rows(filtered_rows, sort_key, sort_dir)
        total = len(sorted_rows)
        page_rows = sorted_rows[offset:offset + limit] if limit is not None else sorted_rows
        return page_rows, total, custom_metric_columns

    # Cache Management Operations
    def get_subrun_id(self, parent_session_id, name):
        result = self.backend.get_subrun_by_parent_and_name_query(parent_session_id, name)
        if result is None:
            return None
        else:
            return result["session_id"]

    def get_parent_session_id(self, session_id):
        """
        Get parent session ID with retry logic to handle race conditions.

        Since experiments can be inserted and immediately restarted, there can be a race
        condition where the restart handler tries to read parent_session_id before the
        insert transaction is committed. This method retries a few times with short delays.
        """
        max_retries = 3
        retry_delay = 0.05  # 50ms between retries

        for attempt in range(max_retries):
            result = self.backend.get_parent_session_id_query(session_id)
            if result is not None:
                return result["parent_session_id"]

            if attempt < max_retries - 1:  # Don't sleep on last attempt
                logger.debug(
                    f"Parent session not found for {session_id}, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(retry_delay)

        logger.error(f"Failed to find parent session for {session_id} after {max_retries} attempts")
        raise ResourceNotFoundError(f"Session not found: {session_id}")

    def cache_file(self, file_id, file_name, io_stream):
        """Cache file attachment."""
        if not getattr(self, "cache_attachments", False):
            return
        if self.backend.check_attachment_exists_query(file_id):
            return
        from sovara.common.utils import stream_hash, save_io_stream

        content_hash = stream_hash(io_stream)
        row = self.backend.get_attachment_by_content_hash_query(content_hash)
        if row is not None:
            file_path = row["file_path"]
        else:
            file_path = save_io_stream(io_stream, file_name, self.attachment_cache_dir)
        self.backend.insert_attachment_query(file_id, content_hash, file_path)

    def get_file_path(self, file_id):
        if not getattr(self, "cache_attachments", False):
            return None
        row = self.backend.get_attachment_file_path_query(file_id)
        if row is not None:
            return row["file_path"]
        return None

    def attachment_ids_to_paths(self, attachment_ids):
        file_paths = [self.get_file_path(attachment_id) for attachment_id in attachment_ids]
        return [f for f in file_paths if f is not None]

    def get_in_out(self, input_dict: dict, api_type: str) -> CacheOutput:
        """Get input/output for LLM call, handling caching and overwrites."""
        from sovara.runner.context_manager import get_session_id
        from sovara.common.utils import hash_input, set_seed
        from sovara.runner.monkey_patching.patching_utils import capture_stack_trace

        # Capture stack trace early (before any internal calls pollute it)
        stack_trace = capture_stack_trace()

        input_pickle, _ = func_kwargs_to_json_str(input_dict, api_type)
        input_hash = hash_input(input_pickle)

        session_id = get_session_id()

        occurrence = self._next_occurrence(session_id, input_hash)
        row = self.backend.get_llm_call_by_session_and_hash_query(session_id, input_hash, offset=occurrence)

        if row is None:
            logger.debug(
                f"Cache miss: session_id {str(session_id)[:4]}, input_hash {str(input_hash)[:4]}"
            )
            return CacheOutput(
                input_dict=input_dict,
                output=None,
                node_uuid=None,
                input_pickle=input_pickle,
                input_hash=input_hash,
                session_id=session_id,
                stack_trace=stack_trace,
            )

        node_uuid = row["node_uuid"]
        output = None

        if row["input_overwrite"] is not None:
            logger.debug(
                f"Cache hit (input overwritten): session_id {str(session_id)[:4]}, input_hash {str(input_hash)[:4]}"
            )
            input_dict = json_str_to_original_inp_dict(row["input_overwrite"], input_dict, api_type)

        # TODO We can't distinguish between output and output_overwrite
        if row["output"] is not None:
            output = json_str_to_api_obj(row["output"], api_type)
            logger.debug(
                f"Cache hit (output set): session_id {str(session_id)[:4]}, input_hash {str(input_hash)[:4]}"
            )

        set_seed(node_uuid)
        return CacheOutput(
            input_dict=input_dict,
            output=output,
            node_uuid=node_uuid,
            input_pickle=input_pickle,
            input_hash=input_hash,
            session_id=session_id,
            stack_trace=stack_trace,
        )

    def cache_output(
        self, cache_result: CacheOutput, output_obj: Any, api_type: str, cache: bool = True
    ) -> None:
        """Cache the output of an LLM call."""
        from sovara.common.utils import set_seed

        # Reset randomness to avoid generating exact same UUID when re-running
        random.seed()
        if cache_result.node_uuid:
            node_uuid = cache_result.node_uuid
        else:
            node_uuid = str(uuid.uuid4())
        response_ok = api_obj_to_response_ok(output_obj, api_type)

        if response_ok and cache:
            output_json_str = api_obj_to_json_str(output_obj, api_type)
            self.backend.insert_llm_call_with_output_query(
                cache_result.session_id,
                cache_result.input_pickle,
                cache_result.input_hash,
                node_uuid,
                api_type,
                output_json_str,
                cache_result.stack_trace,
            )
            self.checkpoint_active_runtime(cache_result.session_id)
        else:
            logger.warning(f"Node {node_uuid} response not OK.")
        cache_result.node_uuid = node_uuid
        cache_result.output = output_obj
        set_seed(node_uuid)

    def get_finished_runs(self, project_id=None):
        return self.backend.get_finished_runs_query(project_id=project_id, user_id=self.user_id)

    def get_all_experiments_sorted(self, limit=None, offset=0, project_id=None):
        return self.backend.get_all_experiments_sorted_query(limit=limit, offset=offset, project_id=project_id, user_id=self.user_id)

    def get_experiments_by_ids(self, session_ids, project_id=None):
        rows = self.backend.get_experiments_by_ids_query(session_ids, project_id=project_id, user_id=self.user_id)
        return self._attach_tags_to_rows(rows)

    def get_experiments_excluding_ids(self, session_ids, limit=None, offset=0, project_id=None):
        rows = self.backend.get_experiments_excluding_ids_query(session_ids, limit=limit, offset=offset, project_id=project_id, user_id=self.user_id)
        return self._attach_tags_to_rows(rows)

    def get_experiment_count(self, project_id=None):
        return self.backend.get_experiment_count_query(project_id=project_id, user_id=self.user_id)

    def get_experiment_count_excluding_ids(self, session_ids, project_id=None):
        return self.backend.get_experiment_count_excluding_ids_query(session_ids, project_id=project_id, user_id=self.user_id)

    def get_experiments_filtered(self, project_id, exclude_ids, filters, sort_col, sort_dir, limit, offset):
        rows, total = self.backend.query_experiments_filtered(
            project_id,
            exclude_ids,
            filters,
            sort_col,
            sort_dir,
            limit,
            offset,
            user_id=self.user_id,
        )
        return self._attach_tags_to_rows(rows), total

    def get_distinct_versions(self, project_id=None):
        rows = self.backend.get_distinct_versions_query(project_id, user_id=self.user_id)
        return [row["version_date"] for row in rows]

    def get_experiment_detail(self, session_id):
        row = self.backend.get_experiment_detail_query(session_id)
        if row is None:
            return None
        return self._attach_tags_to_rows([row])[0]

    def get_graph(self, session_id):
        return self.backend.get_experiment_graph_topology_query(session_id)

    def get_color_preview(self, session_id):
        row = self.backend.get_experiment_color_preview_query(session_id)
        if row and row["color_preview"]:
            return json.loads(row["color_preview"])
        return []

    def get_parent_environment(self, parent_session_id):
        return self.backend.get_experiment_environment_query(parent_session_id)

    def delete_llm_calls_query(self, session_id):
        return self.backend.delete_llm_calls_query(session_id)

    def delete_all_llm_calls_query(self):
        return self.backend.delete_all_llm_calls_query()

    def update_color_preview(self, session_id, colors):
        color_preview_json = json.dumps(colors)
        self.backend.update_experiment_color_preview_query(color_preview_json, session_id)

    def get_exec_command(self, session_id):
        row = self.backend.get_experiment_exec_info_query(session_id)
        if row is None:
            return None, None, None
        return row["cwd"], row["command"], json.loads(row["environment"])

    def clear_db(self):
        self.backend.delete_all_experiments_query()
        self.backend.delete_all_llm_calls_query()

    def delete_project(self, project_id):
        self.backend.delete_project_query(project_id)

    def delete_runs(self, session_ids):
        return self.backend.delete_experiments_by_ids_query(session_ids, user_id=self.user_id)

    def delete_user(self, user_id):
        self.backend.delete_user_query(user_id)

    def get_session_name(self, session_id):
        row = self.backend.get_session_name_query(session_id)
        if not row:
            return []
        return [row["name"]]

    def query_one_llm_call_input(self, session_id, node_uuid):
        return self.backend.get_llm_call_input_api_type_query(session_id, node_uuid)

    def query_one_llm_call_output(self, session_id, node_uuid):
        return self.backend.get_llm_call_output_api_type_query(session_id, node_uuid)

    def get_next_run_index(self, project_id=None):
        return self.backend.get_next_run_index_query(project_id=project_id, user_id=self.user_id)

    # Project operations
    def get_project(self, project_id):
        return self.backend.get_project_query(project_id)

    def upsert_project(self, project_id, name, description):
        self.backend.upsert_project_query(project_id, name, description)

    def update_project_last_run_at(self, project_id):
        self.backend.update_project_last_run_at_query(project_id)

    def get_all_projects(self):
        return self.backend.get_all_projects_query(user_id=self.user_id)

    def get_project_user_count(self, project_id):
        return self.backend.get_project_user_count_query(project_id)

    # User-project location operations
    def upsert_project_location(self, user_id, project_id, project_location):
        self.backend.upsert_project_location_query(user_id, project_id, project_location)

    def find_project_for_location(self, user_id, path):
        """Find a project whose known location is an ancestor of (or equal to) the given path."""
        rows = self.backend.get_project_at_location_query(user_id, path)
        import os
        path = os.path.abspath(path) + os.sep
        for row in rows:
            loc = os.path.abspath(row["project_location"]) + os.sep
            if path.startswith(loc):
                return row["project_id"], row["project_location"]
        return None

    def get_user_project_locations(self, user_id):
        """Get all project locations for a user across all projects."""
        rows = self.backend.query_all(
            "SELECT project_location FROM user_project_locations WHERE user_id=?", (user_id,)
        )
        return [row["project_location"] for row in rows]

    def get_project_locations(self, user_id, project_id):
        return self.backend.get_project_locations_query(user_id, project_id)

    def get_all_project_locations(self, project_id):
        return self.backend.get_all_project_locations_query(project_id)

    def delete_project_location(self, user_id, project_id, project_location):
        self.backend.delete_project_location_query(user_id, project_id, project_location)

    # Probe-related methods for so-tool
    def get_experiment_metadata(self, session_id):
        return self.backend.get_experiment_metadata_query(session_id)

    def get_llm_calls_for_session(self, session_id):
        return self.backend.get_llm_calls_for_session_query(session_id)

    def get_llm_call_full(self, session_id, node_uuid):
        return self.backend.get_llm_call_full_query(session_id, node_uuid)

    def copy_llm_calls(self, old_session_id, new_session_id):
        self.backend.copy_llm_calls_query(old_session_id, new_session_id)

    # ============================================================
    # Lessons Applied operations (tracks which ao-playbook lessons were applied)
    # ============================================================

    def get_lessons_applied_for_session(self, session_id):
        """Get lesson application records for a specific session."""
        rows = self.backend.get_lessons_applied_for_session_query(session_id)
        return [
            {
                "lesson_id": row["lesson_id"],
                "session_id": row["session_id"],
                "node_uuid": row["node_uuid"],
                "run_name": row["run_name"] or "Unknown Run",
            }
            for row in rows
        ]

    def get_sessions_for_lesson(self, lesson_id):
        rows = self.backend.get_lessons_applied_query(lesson_id)
        return [
            {
                "sessionId": row["session_id"],
                "nodeUuid": row["node_uuid"],
                "runName": row["run_name"] or "Unknown Run",
            }
            for row in rows
        ]

    def add_lesson_applied(self, lesson_id, session_id, node_uuid=None):
        self.backend.add_lesson_applied_query(lesson_id, session_id, node_uuid)

    def remove_lesson_applied(self, lesson_id, session_id, node_uuid=None):
        self.backend.remove_lesson_applied_query(lesson_id, session_id, node_uuid)

    def delete_lessons_applied_for_lesson(self, lesson_id):
        self.backend.delete_lessons_applied_for_lesson_query(lesson_id)


# Create singleton instance following the established pattern
DB = DatabaseManager()
