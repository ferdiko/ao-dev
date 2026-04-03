import json
from collections import defaultdict
from datetime import datetime, timezone

from sovara.common.custom_metrics import MetricColumn, get_metric_kind
from sovara.server.graph_models import RunGraph

from ._shared import BadRequestError, ResourceNotFoundError


class RunsMixin:
    @staticmethod
    def parse_custom_metrics(raw_metrics):
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
    def serialize_timestamp(timestamp):
        if timestamp is None or isinstance(timestamp, str):
            return timestamp
        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is not None:
                timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
            return timestamp.strftime("%Y-%m-%d %H:%M:%S")
        raise TypeError(f"Unsupported timestamp type: {type(timestamp)!r}")

    @staticmethod
    def normalize_thumb_label(raw_value):
        if raw_value is None:
            return None
        return bool(raw_value)

    @staticmethod
    def normalize_runtime_seconds(raw_value):
        if raw_value is None:
            return None
        return max(0.0, float(raw_value))

    def _normalize_run_row(self, row):
        normalized = dict(row)
        normalized["custom_metrics"] = self.parse_custom_metrics(normalized.get("custom_metrics"))
        normalized["thumb_label"] = self.normalize_thumb_label(normalized.get("thumb_label"))
        normalized["runtime_seconds"] = self.normalize_runtime_seconds(normalized.get("runtime_seconds"))
        normalized["active_runtime_seconds"] = self.normalize_runtime_seconds(
            normalized.get("active_runtime_seconds")
        )
        normalized["tags"] = list(normalized.get("tags") or [])
        return normalized

    @staticmethod
    def _normalize_trace_chat_history(raw_value):
        if not raw_value:
            return []

        try:
            parsed = json.loads(raw_value)
        except (TypeError, json.JSONDecodeError):
            return []

        if not isinstance(parsed, list):
            return []

        normalized = []
        for item in parsed:
            if not isinstance(item, dict):
                return []
            role = item.get("role")
            content = item.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str):
                return []
            normalized.append({"role": role, "content": content})
        return normalized

    def _serialize_trace_chat_history(self, history):
        if not isinstance(history, list):
            raise BadRequestError("Trace chat history must be a list.")

        normalized = []
        for index, item in enumerate(history):
            if not isinstance(item, dict):
                raise BadRequestError(f"Trace chat message {index} must be an object.")
            role = item.get("role")
            content = item.get("content")
            if role not in ("user", "assistant"):
                raise BadRequestError(f"Trace chat message {index} has invalid role: {role!r}.")
            if not isinstance(content, str):
                raise BadRequestError(f"Trace chat message {index} content must be a string.")
            normalized.append({"role": role, "content": content})

        return json.dumps(normalized)

    def _get_tags_for_runs_map(self, run_ids):
        rows = self.backend.get_tags_for_runs_query(run_ids)
        tags_by_run: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            tags_by_run[row["run_id"]].append(self._normalize_tag_row(row))
        return tags_by_run

    def _attach_tags_to_rows(self, rows):
        normalized_rows = [self._normalize_run_row(row) for row in rows]
        run_ids = [row["run_id"] for row in normalized_rows]
        tags_by_run = self._get_tags_for_runs_map(run_ids)
        for row in normalized_rows:
            row["tags"] = tags_by_run.get(row["run_id"], [])
        return normalized_rows

    @staticmethod
    def _get_runtime_sort_value(row):
        return (
            row["runtime_seconds"]
            if row["runtime_seconds"] is not None
            else row["active_runtime_seconds"]
        )

    def _matches_custom_metric_filters(self, row, metric_filters):
        metrics = row["custom_metrics"]
        for key, filter_def in metric_filters.items():
            if key not in metrics:
                return False
            value = metrics[key]
            kind = filter_def["kind"] if isinstance(filter_def, dict) else filter_def.kind
            if kind == "bool":
                values = filter_def["values"] if isinstance(filter_def, dict) else filter_def.values
                if value not in values:
                    return False
                continue
            if isinstance(value, bool):
                return False
            min_value = filter_def.get("min") if isinstance(filter_def, dict) else filter_def.min
            max_value = filter_def.get("max") if isinstance(filter_def, dict) else filter_def.max
            if min_value is not None and value < min_value:
                return False
            if max_value is not None and value > max_value:
                return False
        return True

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

    def _sort_run_rows_for_metric(self, rows, sort_key, sort_dir):
        reverse = sort_dir.lower() == "desc"
        metric_key = sort_key.split(":", 1)[1]
        present = [row for row in rows if metric_key in row["custom_metrics"]]
        missing = [row for row in rows if metric_key not in row["custom_metrics"]]
        present.sort(key=lambda row: row["custom_metrics"][metric_key], reverse=reverse)
        return present + missing

    def erase(self, run_id):
        """Erase run data."""
        default_graph = json.dumps({"nodes": [], "edges": []})
        self.backend.delete_llm_calls_query(run_id)
        self.backend.update_run_graph_topology_query(default_graph, run_id)

    def add_run(
        self,
        run_id,
        name,
        timestamp,
        cwd,
        command,
        environment,
        parent_run_id=None,
        version_date=None,
        project_id=None,
        user_id=None,
    ):
        from sovara.common.constants import DEFAULT_LOG, DEFAULT_NOTE

        default_graph = json.dumps({"nodes": [], "edges": []})
        parent_run_id = parent_run_id if parent_run_id else run_id
        env_json = json.dumps(environment)
        serialized_timestamp = self.serialize_timestamp(timestamp)

        self.backend.add_run_query(
            run_id,
            parent_run_id,
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

    def update_graph_topology(self, run_id: str, graph: RunGraph) -> None:
        graph_json = graph.to_json_string()
        self.backend.update_run_graph_topology_query(graph_json, run_id)

    def update_timestamp(self, run_id, timestamp):
        self.backend.update_run_timestamp_query(self.serialize_timestamp(timestamp), run_id)

    def update_runtime_seconds(self, run_id, runtime_seconds):
        normalized = self.normalize_runtime_seconds(runtime_seconds)
        self.backend.update_run_runtime_seconds_query(normalized, run_id)

    def update_active_runtime_seconds(self, run_id, active_runtime_seconds):
        normalized = self.normalize_runtime_seconds(active_runtime_seconds)
        self.backend.update_run_active_runtime_seconds_query(normalized, run_id)

    def clear_active_runtime_seconds(self, run_id):
        self.backend.clear_run_active_runtime_seconds_query(run_id)

    def checkpoint_active_runtime(self, run_id, active_runtime_seconds=None):
        if active_runtime_seconds is None:
            from sovara.runner.context_manager import get_run_runtime_seconds

            active_runtime_seconds = get_run_runtime_seconds(run_id)
        if active_runtime_seconds is None:
            return None
        normalized = self.normalize_runtime_seconds(active_runtime_seconds)
        self.backend.update_run_active_runtime_seconds_query(normalized, run_id)
        return normalized

    def finalize_runtime(self, run_id, runtime_seconds):
        normalized = self.normalize_runtime_seconds(runtime_seconds)
        self.backend.finalize_run_runtime_query(normalized, run_id)
        return normalized

    def update_run_name(self, run_id, name):
        self.backend.update_run_name_query(name, run_id)

    def update_thumb_label(self, run_id, thumb_label):
        self.backend.update_run_thumb_label_query(thumb_label, run_id)

    def update_notes(self, run_id, notes):
        self.backend.update_run_notes_query(notes, run_id)

    def update_command(self, run_id, command):
        self.backend.update_run_command_query(command, run_id)

    def get_trace_chat_history(self, run_id):
        row = self.backend.get_run_trace_chat_history_query(run_id)
        if row is None:
            raise ResourceNotFoundError(f"Run not found: {run_id}")
        return self._normalize_trace_chat_history(row["trace_chat_history"])

    def update_trace_chat_history(self, run_id, history):
        existing = self.backend.get_run_trace_chat_history_query(run_id)
        if existing is None:
            raise ResourceNotFoundError(f"Run not found: {run_id}")
        self.backend.update_run_trace_chat_history_query(
            self._serialize_trace_chat_history(history),
            run_id,
        )

    def clear_trace_chat_history(self, run_id):
        existing = self.backend.get_run_trace_chat_history_query(run_id)
        if existing is None:
            raise ResourceNotFoundError(f"Run not found: {run_id}")
        self.backend.update_run_trace_chat_history_query("[]", run_id)

    def update_run_version_date(self, run_id, version_date):
        self.backend.update_run_version_date_query(
            self.serialize_timestamp(version_date),
            run_id,
        )

    def add_metrics(self, run_id, metrics):
        row = self.backend.get_run_metrics_context_query(run_id)
        if row is None:
            raise ValueError(f"Unknown run_id: {run_id}")

        existing_metrics = self.parse_custom_metrics(row["custom_metrics"])
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
                        f"Metric '{key}' is already registered as kind '{existing_kind}' "
                        "for this project."
                    )
            for key, value in metrics.items():
                if key not in existing_kinds:
                    self.backend.upsert_project_metric_kind_query(
                        project_id,
                        key,
                        get_metric_kind(value),
                    )

        updated_metrics = {**existing_metrics, **metrics}
        self.backend.update_run_custom_metrics_query(
            json.dumps(updated_metrics, sort_keys=True),
            run_id,
        )
        return updated_metrics

    def get_run_table_view(self, project_id, exclude_ids, filters, sort_key, sort_dir, limit, offset):
        metric_filters = filters.get("custom_metrics", {})
        metric_sort = sort_key.startswith("metric:")
        base_filters = {
            "name": filters.get("name"),
            "run_id": filters.get("run_id"),
            "version_date": filters.get("version_date"),
            "timestamp_from": filters.get("timestamp_from"),
            "timestamp_to": filters.get("timestamp_to"),
            "latency_min": filters.get("latency_min"),
            "latency_max": filters.get("latency_max"),
            "thumb_label": filters.get("thumb_label", []),
            "tag_ids": filters.get("tag_ids", []),
        }

        if metric_filters or metric_sort:
            rows, _ = self.backend.query_runs_filtered(
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
                if self._matches_custom_metric_filters(row, metric_filters)
            ]
            custom_metric_columns = self._build_custom_metric_columns(filtered_rows)
            if metric_sort:
                sorted_rows = self._sort_run_rows_for_metric(filtered_rows, sort_key, sort_dir)
            else:
                sorted_rows = filtered_rows
            total = len(sorted_rows)
            page_rows = sorted_rows[offset:offset + limit] if limit is not None else sorted_rows
            return page_rows, total, custom_metric_columns

        rows, total = self.backend.query_runs_filtered(
            project_id,
            exclude_ids,
            base_filters,
            sort_key,
            sort_dir,
            limit,
            offset,
            user_id=self.user_id,
        )
        return self._attach_tags_to_rows(rows), total, []

    def get_finished_runs(self, project_id=None):
        return self.backend.get_finished_runs_query(project_id=project_id, user_id=self.user_id)

    def get_all_runs_sorted(self, limit=None, offset=0, project_id=None):
        rows = self.backend.get_all_runs_sorted_query(
            limit=limit,
            offset=offset,
            project_id=project_id,
            user_id=self.user_id,
        )
        return self._attach_tags_to_rows(rows)

    def get_runs_by_ids(self, run_ids, project_id=None):
        rows = self.backend.get_runs_by_ids_query(run_ids, project_id=project_id, user_id=self.user_id)
        return self._attach_tags_to_rows(rows)

    def get_runs_excluding_ids(self, run_ids, limit=None, offset=0, project_id=None):
        rows = self.backend.get_runs_excluding_ids_query(
            run_ids,
            limit=limit,
            offset=offset,
            project_id=project_id,
            user_id=self.user_id,
        )
        return self._attach_tags_to_rows(rows)

    def get_run_count(self, project_id=None):
        return self.backend.get_run_count_query(project_id=project_id, user_id=self.user_id)

    def get_run_count_excluding_ids(self, run_ids, project_id=None):
        return self.backend.get_run_count_excluding_ids_query(
            run_ids,
            project_id=project_id,
            user_id=self.user_id,
        )

    def get_runs_filtered(self, project_id, exclude_ids, filters, sort_col, sort_dir, limit, offset):
        rows, total = self.backend.query_runs_filtered(
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

    def get_run_detail(self, run_id):
        row = self.backend.get_run_detail_query(run_id)
        if row is None:
            return None
        return self._attach_tags_to_rows([row])[0]

    def get_graph(self, run_id):
        return self.backend.get_run_graph_topology_query(run_id)

    def get_color_preview(self, run_id):
        row = self.backend.get_run_color_preview_query(run_id)
        if row and row["color_preview"]:
            return json.loads(row["color_preview"])
        return []

    def get_parent_environment(self, parent_run_id):
        return self.backend.get_run_environment_query(parent_run_id)

    def update_color_preview(self, run_id, colors):
        color_preview_json = json.dumps(colors)
        self.backend.update_run_color_preview_query(color_preview_json, run_id)

    def get_exec_command(self, run_id):
        row = self.backend.get_run_exec_info_query(run_id)
        if row is None:
            return None, None, None
        return row["cwd"], row["command"], json.loads(row["environment"])

    def clear_db(self):
        self.backend.delete_all_runs_query()
        self.backend.delete_all_llm_calls_query()

    def delete_runs(self, run_ids):
        return self.backend.delete_runs_by_ids_query(run_ids, user_id=self.user_id)

    def delete_runs_by_ids(self, run_ids, user_id=None):
        return self.backend.delete_runs_by_ids_query(run_ids, user_id=user_id)

    def get_run_name(self, run_id):
        row = self.backend.get_run_name_query(run_id)
        if not row:
            return []
        return [row["name"]]

    def find_run_ids_by_prefix(self, run_id_prefix):
        rows = self.backend.find_run_ids_by_prefix_query(run_id_prefix)
        return [row["run_id"] for row in rows]

    def get_next_run_index(self, project_id=None):
        return self.backend.get_next_run_index_query(project_id=project_id, user_id=self.user_id)

    def get_run_metadata(self, run_id):
        row = self.backend.get_run_metadata_query(run_id)
        if row is None:
            return None
        return self._normalize_run_row(row)
