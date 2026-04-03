from .connection import execute, query_all, query_one


_RUN_LIST_SELECT = """
    r.run_id,
    r.project_id,
    r.timestamp,
    r.runtime_seconds,
    r.active_runtime_seconds,
    r.color_preview,
    r.name,
    r.version_date,
    r.custom_metrics,
    r.thumb_label
"""

_LABEL_SORT_SQL = "CASE WHEN r.thumb_label IS NULL THEN -1 WHEN r.thumb_label = 0 THEN 0 ELSE 1 END"
_LATENCY_SQL = "COALESCE(r.runtime_seconds, r.active_runtime_seconds)"
_TAGS_SORT_SQL = """
COALESCE((
    SELECT GROUP_CONCAT(name, ',')
    FROM (
        SELECT pt.name AS name
        FROM run_tags rt
        JOIN project_tags pt ON pt.tag_id = rt.tag_id
        WHERE rt.run_id = r.run_id
        ORDER BY LOWER(pt.name) ASC, pt.tag_id ASC
    )
), '')
"""


def add_run_query(
    run_id,
    parent_run_id,
    name,
    default_graph,
    timestamp,
    cwd,
    command,
    env_json,
    default_note,
    default_log,
    version_date,
    project_id=None,
    user_id=None,
):
    execute(
        """
        INSERT OR REPLACE INTO runs (
            run_id,
            parent_run_id,
            project_id,
            user_id,
            name,
            graph_topology,
            timestamp,
            runtime_seconds,
            active_runtime_seconds,
            cwd,
            command,
            environment,
            version_date,
            custom_metrics,
            thumb_label,
            notes,
            log,
            trace_chat_history
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            parent_run_id,
            project_id,
            user_id,
            name,
            default_graph,
            timestamp,
            None,
            None,
            cwd,
            command,
            env_json,
            version_date,
            "{}",
            None,
            default_note,
            default_log,
            "[]",
        ),
    )


def update_run_graph_topology_query(graph_json, run_id):
    execute("UPDATE runs SET graph_topology=? WHERE run_id=?", (graph_json, run_id))


def update_run_timestamp_query(timestamp, run_id):
    execute("UPDATE runs SET timestamp=? WHERE run_id=?", (timestamp, run_id))


def update_run_runtime_seconds_query(runtime_seconds, run_id):
    execute("UPDATE runs SET runtime_seconds=? WHERE run_id=?", (runtime_seconds, run_id))


def update_run_active_runtime_seconds_query(active_runtime_seconds, run_id):
    execute(
        "UPDATE runs SET active_runtime_seconds=? WHERE run_id=?",
        (active_runtime_seconds, run_id),
    )


def finalize_run_runtime_query(runtime_seconds, run_id):
    execute(
        """
        UPDATE runs
        SET runtime_seconds=COALESCE(runtime_seconds, ?),
            active_runtime_seconds=NULL
        WHERE run_id=?
        """,
        (runtime_seconds, run_id),
    )


def clear_run_active_runtime_seconds_query(run_id):
    execute("UPDATE runs SET active_runtime_seconds=NULL WHERE run_id=?", (run_id,))


def update_run_name_query(name, run_id):
    execute("UPDATE runs SET name=? WHERE run_id=?", (name, run_id))


def update_run_notes_query(notes, run_id):
    execute("UPDATE runs SET notes=? WHERE run_id=?", (notes, run_id))


def get_run_trace_chat_history_query(run_id):
    return query_one("SELECT trace_chat_history FROM runs WHERE run_id=?", (run_id,))


def update_run_trace_chat_history_query(trace_chat_history, run_id):
    execute("UPDATE runs SET trace_chat_history=? WHERE run_id=?", (trace_chat_history, run_id))


def update_run_command_query(command, run_id):
    execute("UPDATE runs SET command=? WHERE run_id=?", (command, run_id))


def update_run_version_date_query(version_date, run_id):
    execute("UPDATE runs SET version_date=? WHERE run_id=?", (version_date, run_id))


def update_run_log_query(updated_log, graph_json, run_id):
    execute("UPDATE runs SET log=?, graph_topology=? WHERE run_id=?", (updated_log, graph_json, run_id))


def update_run_custom_metrics_query(custom_metrics_json, run_id):
    execute("UPDATE runs SET custom_metrics=? WHERE run_id=?", (custom_metrics_json, run_id))


def update_run_thumb_label_query(thumb_label, run_id):
    db_value = None if thumb_label is None else int(thumb_label)
    execute("UPDATE runs SET thumb_label=? WHERE run_id=?", (db_value, run_id))


def get_run_metrics_context_query(run_id):
    return query_one("SELECT project_id, custom_metrics FROM runs WHERE run_id=?", (run_id,))


def get_run_tag_context_query(run_id):
    return query_one("SELECT project_id, user_id FROM runs WHERE run_id=?", (run_id,))


def get_finished_runs_query(project_id=None, user_id=None):
    conditions, params = [], []
    if project_id:
        conditions.append("project_id=?")
        params.append(project_id)
    if user_id:
        conditions.append("user_id=?")
        params.append(user_id)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    return query_all(f"SELECT run_id, timestamp FROM runs{where} ORDER BY timestamp DESC", tuple(params))


def get_all_runs_sorted_query(limit=None, offset=0, project_id=None, user_id=None):
    conditions, params = [], []
    if project_id:
        conditions.append("project_id=?")
        params.append(project_id)
    if user_id:
        conditions.append("user_id=?")
        params.append(user_id)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT {_RUN_LIST_SELECT} FROM runs r{where} ORDER BY r.timestamp DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return query_all(sql, tuple(params))


def get_runs_by_ids_query(run_ids, project_id=None, user_id=None):
    if not run_ids:
        return []
    placeholders = ",".join("?" * len(run_ids))
    params = list(run_ids)
    conditions = [f"r.run_id IN ({placeholders})"]
    if project_id:
        conditions.append("r.project_id=?")
        params.append(project_id)
    if user_id:
        conditions.append("r.user_id=?")
        params.append(user_id)
    sql = f"SELECT {_RUN_LIST_SELECT} FROM runs r WHERE {' AND '.join(conditions)} ORDER BY r.timestamp DESC"
    return query_all(sql, tuple(params))


def get_runs_excluding_ids_query(run_ids, limit=None, offset=0, project_id=None, user_id=None):
    if not run_ids:
        return get_all_runs_sorted_query(
            limit=limit,
            offset=offset,
            project_id=project_id,
            user_id=user_id,
        )
    placeholders = ",".join("?" * len(run_ids))
    params = list(run_ids)
    conditions = [f"r.run_id NOT IN ({placeholders})"]
    if project_id:
        conditions.append("r.project_id=?")
        params.append(project_id)
    if user_id:
        conditions.append("r.user_id=?")
        params.append(user_id)
    sql = f"SELECT {_RUN_LIST_SELECT} FROM runs r WHERE {' AND '.join(conditions)} ORDER BY r.timestamp DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return query_all(sql, tuple(params))


def get_run_count_excluding_ids_query(run_ids, project_id=None, user_id=None):
    if not run_ids:
        return get_run_count_query(project_id=project_id, user_id=user_id)
    placeholders = ",".join("?" * len(run_ids))
    params = list(run_ids)
    conditions = [f"run_id NOT IN ({placeholders})"]
    if project_id:
        conditions.append("project_id=?")
        params.append(project_id)
    if user_id:
        conditions.append("user_id=?")
        params.append(user_id)
    row = query_one(
        f"SELECT COUNT(*) as count FROM runs WHERE {' AND '.join(conditions)}",
        tuple(params),
    )
    return row["count"] if row else 0


def get_run_count_query(project_id=None, user_id=None):
    conditions, params = [], []
    if project_id:
        conditions.append("project_id=?")
        params.append(project_id)
    if user_id:
        conditions.append("user_id=?")
        params.append(user_id)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    row = query_one(f"SELECT COUNT(*) as count FROM runs{where}", tuple(params))
    return row["count"] if row else 0


def _normalize_timestamp_filter_value(value, end_of_range=False):
    normalized = str(value).strip().replace("T", " ")
    if len(normalized) == 10:
        return normalized + (" 23:59:59" if end_of_range else " 00:00:00")
    if len(normalized) == 16:
        return normalized + (":59" if end_of_range else ":00")
    return normalized


def _build_run_filters(filters):
    filters = filters or {}
    conditions = []
    params = []

    if filters.get("name"):
        conditions.append("LOWER(r.name) LIKE ?")
        params.append(f"%{filters['name'].lower()}%")
    if filters.get("run_id"):
        conditions.append("LOWER(r.run_id) LIKE ?")
        params.append(f"%{filters['run_id'].lower()}%")
    if filters.get("version_date"):
        values = filters["version_date"]
        placeholders = ",".join("?" * len(values))
        conditions.append(f"r.version_date IN ({placeholders})")
        params.extend(values)
    if filters.get("timestamp_from"):
        conditions.append("r.timestamp >= ?")
        params.append(_normalize_timestamp_filter_value(filters["timestamp_from"], end_of_range=False))
    if filters.get("timestamp_to"):
        conditions.append("r.timestamp <= ?")
        params.append(_normalize_timestamp_filter_value(filters["timestamp_to"], end_of_range=True))
    if filters.get("latency_min") is not None:
        conditions.append(f"{_LATENCY_SQL} >= ?")
        params.append(filters["latency_min"])
    if filters.get("latency_max") is not None:
        conditions.append(f"{_LATENCY_SQL} <= ?")
        params.append(filters["latency_max"])

    label_tokens = [token for token in filters.get("thumb_label", []) if token in {"up", "down", "none"}]
    if label_tokens:
        label_conditions = []
        if "up" in label_tokens:
            label_conditions.append("r.thumb_label = 1")
        if "down" in label_tokens:
            label_conditions.append("r.thumb_label = 0")
        if "none" in label_tokens:
            label_conditions.append("r.thumb_label IS NULL")
        conditions.append("(" + " OR ".join(label_conditions) + ")")

    for tag_id in filters.get("tag_ids", []) or []:
        conditions.append(
            """
            EXISTS (
                SELECT 1
                FROM run_tags rt
                WHERE rt.run_id = r.run_id AND rt.tag_id = ?
            )
            """.strip()
        )
        params.append(tag_id)

    return conditions, params


def _resolve_run_order(sort_col, sort_dir):
    sort_key = {
        "runId": "run_id",
        "codeVersion": "version_date",
    }.get(sort_col, sort_col)
    direction = "DESC" if str(sort_dir).upper() != "ASC" else "ASC"

    if sort_key == "run_id":
        expr = "r.run_id"
        return f"{expr} IS NULL ASC, {expr} {direction}"
    if sort_key == "name":
        expr = "r.name"
        return f"{expr} IS NULL ASC, {expr} {direction}"
    if sort_key == "version_date":
        expr = "r.version_date"
        return f"{expr} IS NULL ASC, {expr} {direction}"
    if sort_key == "label":
        return f"{_LABEL_SORT_SQL} {direction}"
    if sort_key == "latency":
        return f"{_LATENCY_SQL} IS NULL ASC, {_LATENCY_SQL} {direction}"
    if sort_key == "tags":
        return f"{_TAGS_SORT_SQL} {direction}"
    expr = "r.timestamp"
    return f"{expr} IS NULL ASC, {expr} {direction}"


def query_runs_filtered(project_id, exclude_ids, filters, sort_col, sort_dir, limit, offset, user_id=None):
    conditions = []
    params = []
    if project_id:
        conditions.append("r.project_id=?")
        params.append(project_id)
    if user_id:
        conditions.append("r.user_id=?")
        params.append(user_id)
    if exclude_ids:
        placeholders = ",".join("?" * len(exclude_ids))
        conditions.append(f"r.run_id NOT IN ({placeholders})")
        params.extend(exclude_ids)

    filter_conditions, filter_params = _build_run_filters(filters)
    conditions.extend(filter_conditions)
    params.extend(filter_params)

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    order_by = _resolve_run_order(sort_col, sort_dir)
    count_row = query_one(f"SELECT COUNT(*) as count FROM runs r{where}", tuple(params))
    total = count_row["count"] if count_row else 0

    sql = f"SELECT {_RUN_LIST_SELECT} FROM runs r{where} ORDER BY {order_by}"
    data_params = list(params)
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        data_params.extend([limit, offset])
    rows = query_all(sql, tuple(data_params))
    return rows, total


def get_distinct_versions_query(project_id=None, user_id=None):
    conditions = ["version_date IS NOT NULL"]
    params = []
    if project_id:
        conditions.append("project_id=?")
        params.append(project_id)
    if user_id:
        conditions.append("user_id=?")
        params.append(user_id)
    return query_all(
        f"SELECT DISTINCT version_date FROM runs WHERE {' AND '.join(conditions)} ORDER BY version_date DESC",
        tuple(params),
    )


def get_run_detail_query(run_id):
    return query_one(
        """
        SELECT run_id, project_id, name, timestamp, runtime_seconds, active_runtime_seconds,
               custom_metrics, thumb_label, notes, log, version_date
        FROM runs
        WHERE run_id=?
        """,
        (run_id,),
    )


def get_run_graph_topology_query(run_id):
    return query_one("SELECT graph_topology FROM runs WHERE run_id=?", (run_id,))


def get_run_color_preview_query(run_id):
    return query_one("SELECT color_preview FROM runs WHERE run_id=?", (run_id,))


def get_run_environment_query(parent_run_id):
    return query_one(
        "SELECT cwd, command, environment FROM runs WHERE run_id=?",
        (parent_run_id,),
    )


def update_run_color_preview_query(color_preview_json, run_id):
    execute("UPDATE runs SET color_preview=? WHERE run_id=?", (color_preview_json, run_id))


def get_run_exec_info_query(run_id):
    return query_one("SELECT cwd, command, environment FROM runs WHERE run_id=?", (run_id,))


def delete_all_runs_query():
    execute("DELETE FROM run_tags")
    execute("DELETE FROM runs")


def _delete_runs_data(run_ids):
    if not run_ids:
        return
    placeholders = ",".join("?" * len(run_ids))
    ids = tuple(run_ids)
    execute(f"DELETE FROM run_tags WHERE run_id IN ({placeholders})", ids)
    execute(f"DELETE FROM llm_calls WHERE run_id IN ({placeholders})", ids)
    execute(f"DELETE FROM priors_applied WHERE run_id IN ({placeholders})", ids)
    execute(f"DELETE FROM runs WHERE run_id IN ({placeholders})", ids)


def delete_runs_by_ids_query(run_ids, user_id=None):
    if not run_ids:
        return 0

    unique_ids = list(dict.fromkeys(run_ids))
    if user_id:
        placeholders = ",".join("?" * len(unique_ids))
        rows = query_all(
            f"SELECT run_id FROM runs WHERE user_id=? AND run_id IN ({placeholders})",
            (user_id, *unique_ids),
        )
        unique_ids = [row["run_id"] for row in rows]

    if not unique_ids:
        return 0

    placeholders = ",".join("?" * len(unique_ids))
    project_rows = query_all(
        f"""
        SELECT DISTINCT project_id
        FROM runs
        WHERE run_id IN ({placeholders}) AND project_id IS NOT NULL
        """,
        tuple(unique_ids),
    )
    project_ids = [row["project_id"] for row in project_rows]

    _delete_runs_data(unique_ids)

    for project_id in project_ids:
        row = query_one(
            "SELECT MAX(timestamp) AS last_run_at FROM runs WHERE project_id=?",
            (project_id,),
        )
        execute(
            "UPDATE projects SET last_run_at=? WHERE project_id=?",
            ((row["last_run_at"] if row else None), project_id),
        )

    return len(unique_ids)


def get_run_name_query(run_id):
    return query_one("SELECT name FROM runs WHERE run_id=?", (run_id,))


def find_run_ids_by_prefix_query(run_id_prefix):
    return query_all(
        """
        SELECT run_id
        FROM runs
        WHERE REPLACE(LOWER(run_id), '-', '') LIKE ?
        ORDER BY timestamp DESC
        """,
        (f"{run_id_prefix.lower()}%",),
    )


def get_run_log_success_graph_query(run_id):
    return query_one(
        "SELECT log, graph_topology FROM runs WHERE run_id=?",
        (run_id,),
    )


def get_next_run_index_query(project_id=None, user_id=None):
    conditions, params = [], []
    if project_id:
        conditions.append("project_id=?")
        params.append(project_id)
    if user_id:
        conditions.append("user_id=?")
        params.append(user_id)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    row = query_one(f"SELECT COUNT(*) as count FROM runs{where}", tuple(params))
    if row:
        return row["count"] + 1
    return 1


def get_run_metadata_query(run_id):
    return query_one(
        """
        SELECT run_id, parent_run_id, name, timestamp, custom_metrics, thumb_label, notes, log,
               graph_topology, version_date
        FROM runs
        WHERE run_id=?
        """,
        (run_id,),
    )
