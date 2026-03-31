"""
SQLite database backend for workflow runs.

Uses per-thread connections via threading.local() so readers can run concurrently
under WAL mode. Writers still serialize at the SQLite level (WAL allows only one
writer at a time), but that's SQLite's own locking — not a Python bottleneck.
"""

import os
import sqlite3
import threading

from sovara.common.logger import logger
from sovara.common.constants import SOVARA_DB_PATH


# Per-thread connection storage. Each thread gets its own sqlite3.Connection,
# avoiding the need for a global lock that serializes all DB operations.
_local = threading.local()

# One-time schema initialization
_schema_initialized = False
_init_lock = threading.Lock()


def get_conn():
    """Get a per-thread SQLite connection, creating one if needed."""
    global _schema_initialized

    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn

    db_path = os.path.join(SOVARA_DB_PATH, "runs.sqlite")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(
        db_path,
        timeout=30.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")

    # Initialize schema once (first thread to connect)
    if not _schema_initialized:
        with _init_lock:
            if not _schema_initialized:
                _init_db(conn)
                _schema_initialized = True

    _local.conn = conn
    return conn


def _init_db(conn):
    c = conn.cursor()

    # Create users table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT (datetime('now'))
        )
    """
    )

    # Create projects table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT (datetime('now')),
            last_run_at TIMESTAMP
        )
    """
    )

    # Create runs table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            parent_run_id TEXT,
            project_id TEXT,
            user_id TEXT,
            graph_topology TEXT,
            color_preview TEXT,
            timestamp TIMESTAMP DEFAULT (datetime('now')),
            runtime_seconds REAL,
            active_runtime_seconds REAL,
            cwd TEXT,
            command TEXT,
            environment TEXT,
            version_date TEXT,
            name TEXT,
            success TEXT CHECK (success IN ('', 'Satisfactory', 'Failed')),
            custom_metrics TEXT NOT NULL DEFAULT '{}',
            thumb_label INTEGER CHECK (thumb_label IN (0, 1)),
            notes TEXT,
            log TEXT,
            trace_chat_history TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY (parent_run_id) REFERENCES runs (run_id),
            FOREIGN KEY (project_id) REFERENCES projects (project_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            UNIQUE (parent_run_id, name)
        )
    """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS project_metric_kinds (
            project_id TEXT NOT NULL,
            metric_key TEXT NOT NULL,
            metric_kind TEXT NOT NULL CHECK (metric_kind IN ('bool', 'int', 'float')),
            PRIMARY KEY (project_id, metric_key),
            FOREIGN KEY (project_id) REFERENCES projects (project_id)
        )
    """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS project_tags (
            tag_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL COLLATE NOCASE,
            color TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects (project_id),
            UNIQUE (project_id, name)
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS run_tags (
            run_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            PRIMARY KEY (run_id, tag_id),
            FOREIGN KEY (run_id) REFERENCES runs (run_id),
            FOREIGN KEY (tag_id) REFERENCES project_tags (tag_id)
        )
    """
    )
    # Create llm_calls table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_calls (
            run_id TEXT,
            node_uuid TEXT,
            input TEXT,
            input_hash TEXT,
            input_overwrite TEXT,
            output TEXT,
            color TEXT,
            label TEXT,
            api_type TEXT,
            stack_trace TEXT,
            timestamp TIMESTAMP DEFAULT (datetime('now')),
            PRIMARY KEY (run_id, node_uuid),
            FOREIGN KEY (run_id) REFERENCES runs (run_id)
        )
    """
    )
    # Create attachments table (for caching file attachments like images)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS attachments (
            file_id TEXT PRIMARY KEY,
            content_hash TEXT,
            file_path TEXT
        )
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS attachments_content_hash_idx ON attachments(content_hash)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS original_input_lookup ON llm_calls(run_id, input_hash)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS runs_timestamp_idx ON runs(timestamp DESC)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS runs_project_idx ON runs(project_id, timestamp DESC)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS project_tags_project_idx ON project_tags(project_id, name)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS run_tags_run_idx ON run_tags(run_id)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS run_tags_tag_idx ON run_tags(tag_id)
    """
    )

    # Create user_project_locations table (links users to project locations on disk)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS user_project_locations (
            user_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            project_location TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (project_id) REFERENCES projects (project_id),
            UNIQUE (user_id, project_location)
        )
    """
    )

    # Create priors_applied table (tracks which priors from SovaraDB were applied to runs)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS priors_applied (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prior_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            node_uuid TEXT,
            applied_at TIMESTAMP DEFAULT (datetime('now')),
            FOREIGN KEY (run_id) REFERENCES runs (run_id),
            UNIQUE (prior_id, run_id, node_uuid)
        )
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS priors_applied_prior_idx ON priors_applied(prior_id)
    """
    )

    conn.commit()
    _ensure_run_schema(conn)


def _ensure_run_schema(conn):
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(runs)").fetchall()
    }
    if "custom_metrics" not in columns:
        conn.execute("ALTER TABLE runs ADD COLUMN custom_metrics TEXT NOT NULL DEFAULT '{}'")
    if "thumb_label" not in columns:
        conn.execute("ALTER TABLE runs ADD COLUMN thumb_label INTEGER CHECK (thumb_label IN (0, 1))")
    if "runtime_seconds" not in columns:
        conn.execute("ALTER TABLE runs ADD COLUMN runtime_seconds REAL")
    if "active_runtime_seconds" not in columns:
        conn.execute("ALTER TABLE runs ADD COLUMN active_runtime_seconds REAL")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_metric_kinds (
            project_id TEXT NOT NULL,
            metric_key TEXT NOT NULL,
            metric_kind TEXT NOT NULL CHECK (metric_kind IN ('bool', 'int', 'float')),
            PRIMARY KEY (project_id, metric_key),
            FOREIGN KEY (project_id) REFERENCES projects (project_id)
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_tags (
            tag_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL COLLATE NOCASE,
            color TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects (project_id),
            UNIQUE (project_id, name)
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_tags (
            run_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            PRIMARY KEY (run_id, tag_id),
            FOREIGN KEY (run_id) REFERENCES runs (run_id),
            FOREIGN KEY (tag_id) REFERENCES project_tags (tag_id)
        )
    """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS project_tags_project_idx ON project_tags(project_id, name)
    """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS run_tags_run_idx ON run_tags(run_id)
    """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS run_tags_tag_idx ON run_tags(tag_id)
    """
    )
    conn.commit()


def query_one(sql, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute(sql, params)
    return c.fetchone()


def query_all(sql, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute(sql, params)
    return c.fetchall()


def execute(sql, params=()):
    """Execute SQL (each thread uses its own connection)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(sql, params)
    conn.commit()
    return c.lastrowid


def clear_connections():
    """Close the calling thread's connection."""
    conn = getattr(_local, "conn", None)
    if conn:
        try:
            conn.close()
        except Exception as e:
            logger.warning(f"Error closing SQLite connection: {e}")
        finally:
            _local.conn = None
        logger.debug("Closed thread-local SQLite connection")


def upsert_user_query(user_id, full_name, email):
    """Insert user if new, update name/email if existing."""
    execute(
        "INSERT OR IGNORE INTO users (user_id, full_name, email) VALUES (?, ?, ?)",
        (user_id, full_name, email),
    )
    execute(
        "UPDATE users SET full_name=?, email=? WHERE user_id=?",
        (full_name, email, user_id),
    )


def get_user_query(user_id):
    """Get user by user_id."""
    return query_one("SELECT user_id, full_name, email FROM users WHERE user_id=?", (user_id,))


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
    """Execute SQLite-specific INSERT for runs table"""
    execute(
        "INSERT OR REPLACE INTO runs (run_id, parent_run_id, project_id, user_id, name, graph_topology, timestamp, runtime_seconds, active_runtime_seconds, cwd, command, environment, version_date, custom_metrics, thumb_label, notes, log, trace_chat_history) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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


def set_input_overwrite_query(input_overwrite, run_id, node_uuid):
    """Execute SQLite-specific UPDATE for llm_calls input_overwrite"""
    execute(
        "UPDATE llm_calls SET input_overwrite=?, output=NULL WHERE run_id=? AND node_uuid=?",
        (input_overwrite, run_id, node_uuid),
    )


def set_output_overwrite_query(output_overwrite, run_id, node_uuid):
    """Execute SQLite-specific UPDATE for llm_calls output"""
    execute(
        "UPDATE llm_calls SET output=? WHERE run_id=? AND node_uuid=?",
        (output_overwrite, run_id, node_uuid),
    )


def delete_llm_calls_query(run_id):
    """Execute SQLite-specific DELETE for llm_calls"""
    execute("DELETE FROM llm_calls WHERE run_id=?", (run_id,))


def update_run_graph_topology_query(graph_json, run_id):
    """Execute SQLite-specific UPDATE for runs graph_topology"""
    execute("UPDATE runs SET graph_topology=? WHERE run_id=?", (graph_json, run_id))


def update_run_timestamp_query(timestamp, run_id):
    """Execute SQLite-specific UPDATE for runs timestamp"""
    execute("UPDATE runs SET timestamp=? WHERE run_id=?", (timestamp, run_id))


def update_run_runtime_seconds_query(runtime_seconds, run_id):
    """Persist the canonical completed runtime for an run."""
    execute(
        "UPDATE runs SET runtime_seconds=? WHERE run_id=?",
        (runtime_seconds, run_id),
    )


def update_run_active_runtime_seconds_query(active_runtime_seconds, run_id):
    """Persist the latest runtime checkpoint for an run."""
    execute(
        "UPDATE runs SET active_runtime_seconds=? WHERE run_id=?",
        (active_runtime_seconds, run_id),
    )


def finalize_run_runtime_query(runtime_seconds, run_id):
    """Finalize a run attempt without overwriting an existing canonical runtime."""
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
    """Clear the active runtime checkpoint for an run."""
    execute(
        "UPDATE runs SET active_runtime_seconds=NULL WHERE run_id=?",
        (run_id,),
    )


def update_run_name_query(name, run_id):
    """Execute SQLite-specific UPDATE for runs name"""
    execute(
        "UPDATE runs SET name=? WHERE run_id=?",
        (name, run_id),
    )


def update_run_notes_query(notes, run_id):
    """Execute SQLite-specific UPDATE for runs notes"""
    execute(
        "UPDATE runs SET notes=? WHERE run_id=?",
        (notes, run_id),
    )


def get_run_trace_chat_history_query(run_id):
    """Get persisted trace chat history for a single run."""
    return query_one(
        "SELECT trace_chat_history FROM runs WHERE run_id=?",
        (run_id,),
    )


def update_run_trace_chat_history_query(trace_chat_history, run_id):
    """Persist trace chat history for a single run."""
    execute(
        "UPDATE runs SET trace_chat_history=? WHERE run_id=?",
        (trace_chat_history, run_id),
    )


def update_run_command_query(command, run_id):
    """Execute SQLite-specific UPDATE for runs command"""
    execute(
        "UPDATE runs SET command=? WHERE run_id=?",
        (command, run_id),
    )


def update_run_version_date_query(version_date, run_id):
    """Execute SQLite-specific UPDATE for runs version_date"""
    execute(
        "UPDATE runs SET version_date=? WHERE run_id=?",
        (version_date, run_id),
    )


def update_run_log_query(updated_log, graph_json, run_id):
    """Execute SQLite-specific UPDATE for runs log and graph_topology"""
    execute(
        "UPDATE runs SET log=?, graph_topology=? WHERE run_id=?",
        (updated_log, graph_json, run_id),
    )


def update_run_custom_metrics_query(custom_metrics_json, run_id):
    """Execute SQLite-specific UPDATE for runs custom_metrics."""
    execute(
        "UPDATE runs SET custom_metrics=? WHERE run_id=?",
        (custom_metrics_json, run_id),
    )


def update_run_thumb_label_query(thumb_label, run_id):
    """Execute SQLite-specific UPDATE for runs thumb_label."""
    db_value = None if thumb_label is None else int(thumb_label)
    execute(
        "UPDATE runs SET thumb_label=? WHERE run_id=?",
        (db_value, run_id),
    )


def get_run_metrics_context_query(run_id):
    """Get project_id and custom_metrics for an run."""
    return query_one(
        "SELECT project_id, custom_metrics FROM runs WHERE run_id=?",
        (run_id,),
    )


def get_run_tag_context_query(run_id):
    """Get project_id and user_id for an run."""
    return query_one(
        "SELECT project_id, user_id FROM runs WHERE run_id=?",
        (run_id,),
    )


def get_project_tags_query(project_id):
    """Get all tag definitions for a project."""
    return query_all(
        """
        SELECT tag_id, project_id, name, color, created_at
        FROM project_tags
        WHERE project_id=?
        ORDER BY LOWER(name) ASC, tag_id ASC
        """,
        (project_id,),
    )


def get_project_tag_query(tag_id):
    """Get a single project tag by ID."""
    return query_one(
        """
        SELECT tag_id, project_id, name, color, created_at
        FROM project_tags
        WHERE tag_id=?
        """,
        (tag_id,),
    )


def get_project_tag_by_name_query(project_id, name):
    """Get a project tag by name within one project."""
    return query_one(
        """
        SELECT tag_id, project_id, name, color, created_at
        FROM project_tags
        WHERE project_id=? AND name=?
        """,
        (project_id, name),
    )


def get_project_tags_by_ids_query(project_id, tag_ids):
    """Get a project's tags restricted to the provided IDs."""
    if not tag_ids:
        return []
    placeholders = ",".join("?" * len(tag_ids))
    return query_all(
        f"""
        SELECT tag_id, project_id, name, color, created_at
        FROM project_tags
        WHERE project_id=? AND tag_id IN ({placeholders})
        ORDER BY LOWER(name) ASC, tag_id ASC
        """,
        (project_id, *tag_ids),
    )


def insert_project_tag_query(tag_id, project_id, name, color):
    """Insert a new project tag."""
    execute(
        """
        INSERT INTO project_tags (tag_id, project_id, name, color)
        VALUES (?, ?, ?, ?)
        """,
        (tag_id, project_id, name, color),
    )


def delete_project_tag_query(project_id, tag_id):
    """Delete a project tag and all run assignments for it."""
    execute("DELETE FROM run_tags WHERE tag_id=?", (tag_id,))
    execute("DELETE FROM project_tags WHERE project_id=? AND tag_id=?", (project_id, tag_id))


def get_tags_for_runs_query(run_ids):
    """Get assigned tags for one or more runs."""
    if not run_ids:
        return []
    placeholders = ",".join("?" * len(run_ids))
    return query_all(
        f"""
        SELECT et.run_id, pt.tag_id, pt.project_id, pt.name, pt.color, pt.created_at
        FROM run_tags et
        JOIN project_tags pt ON pt.tag_id = et.tag_id
        WHERE et.run_id IN ({placeholders})
        ORDER BY LOWER(pt.name) ASC, pt.tag_id ASC
        """,
        tuple(run_ids),
    )


def replace_run_tags_query(run_id, tag_ids):
    """Replace the complete tag assignment set for a run."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM run_tags WHERE run_id=?", (run_id,))
    if tag_ids:
        cursor.executemany(
            "INSERT INTO run_tags (run_id, tag_id) VALUES (?, ?)",
            [(run_id, tag_id) for tag_id in tag_ids],
        )
    conn.commit()


def get_project_metric_kinds_query(project_id):
    """Get all registered metric kinds for a project."""
    return query_all(
        "SELECT metric_key, metric_kind FROM project_metric_kinds WHERE project_id=? ORDER BY metric_key ASC",
        (project_id,),
    )


def upsert_project_metric_kind_query(project_id, metric_key, metric_kind):
    """Insert or update the registered kind for a project metric."""
    execute(
        """
        INSERT INTO project_metric_kinds (project_id, metric_key, metric_kind)
        VALUES (?, ?, ?)
        ON CONFLICT(project_id, metric_key) DO UPDATE SET metric_kind=excluded.metric_kind
        """,
        (project_id, metric_key, metric_kind),
    )


# Attachment-related queries
def check_attachment_exists_query(file_id):
    """Check if attachment with given file_id exists."""
    return query_one("SELECT file_id FROM attachments WHERE file_id=?", (file_id,))


def get_attachment_by_content_hash_query(content_hash):
    """Get attachment file path by content hash."""
    return query_one("SELECT file_path FROM attachments WHERE content_hash=?", (content_hash,))


def insert_attachment_query(file_id, content_hash, file_path):
    """Insert new attachment record."""
    execute(
        "INSERT INTO attachments (file_id, content_hash, file_path) VALUES (?, ?, ?)",
        (file_id, content_hash, file_path),
    )


def get_attachment_file_path_query(file_id):
    """Get file path for attachment by file_id."""
    return query_one("SELECT file_path FROM attachments WHERE file_id=?", (file_id,))


# Subrun queries
def get_subrun_by_parent_and_name_query(parent_run_id, name):
    """Get subrun run_id by parent run and name."""
    return query_one(
        "SELECT run_id FROM runs WHERE parent_run_id = ? AND name = ?",
        (parent_run_id, name),
    )


def get_parent_run_id_query(run_id):
    """Get parent run ID for a given run."""
    return query_one("SELECT parent_run_id FROM runs WHERE run_id=?", (run_id,))


# LLM calls queries
def get_llm_call_by_run_and_hash_query(run_id, input_hash, offset=0):
    """Get LLM call by run_id and input_hash. offset selects the Nth match."""
    return query_one(
        "SELECT node_uuid, input_overwrite, output FROM llm_calls WHERE run_id=? AND input_hash=? ORDER BY rowid LIMIT 1 OFFSET ?",
        (run_id, input_hash, offset),
    )


def insert_llm_call_with_output_query(
    run_id, input_pickle, input_hash, node_uuid, api_type, output_pickle, stack_trace=None
):
    """Insert new LLM call record with output in a single operation (upsert)."""
    execute(
        """
        INSERT INTO llm_calls (run_id, input, input_hash, node_uuid, api_type, output, stack_trace)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (run_id, node_uuid)
        DO UPDATE SET output = excluded.output, stack_trace = excluded.stack_trace
        """,
        (run_id, input_pickle, input_hash, node_uuid, api_type, output_pickle, stack_trace),
    )


# Run list and graph queries
def get_finished_runs_query(project_id=None, user_id=None):
    """Get all finished runs ordered by timestamp."""
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
    """Get runs sorted by timestamp desc, with optional pagination."""
    conditions, params = [], []
    if project_id:
        conditions.append("project_id=?")
        params.append(project_id)
    if user_id:
        conditions.append("user_id=?")
        params.append(user_id)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT run_id, project_id, timestamp, runtime_seconds, active_runtime_seconds, color_preview, name, version_date, custom_metrics, thumb_label FROM runs{where} ORDER BY timestamp DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return query_all(sql, tuple(params))


def get_runs_by_ids_query(run_ids, project_id=None, user_id=None):
    """Get runs for specific run IDs, sorted by timestamp desc."""
    if not run_ids:
        return []
    placeholders = ",".join("?" * len(run_ids))
    params = list(run_ids)
    sql = f"SELECT run_id, project_id, timestamp, runtime_seconds, active_runtime_seconds, color_preview, name, version_date, custom_metrics, thumb_label FROM runs WHERE run_id IN ({placeholders})"
    if project_id:
        sql += " AND project_id=?"
        params.append(project_id)
    if user_id:
        sql += " AND user_id=?"
        params.append(user_id)
    sql += " ORDER BY timestamp DESC"
    return query_all(sql, tuple(params))


def get_runs_excluding_ids_query(run_ids, limit=None, offset=0, project_id=None, user_id=None):
    """Get runs excluding specific run IDs, sorted by timestamp desc."""
    if not run_ids:
        return get_all_runs_sorted_query(limit=limit, offset=offset, project_id=project_id, user_id=user_id)
    placeholders = ",".join("?" * len(run_ids))
    params = list(run_ids)
    conditions = [f"run_id NOT IN ({placeholders})"]
    if project_id:
        conditions.append("project_id=?")
        params.append(project_id)
    if user_id:
        conditions.append("user_id=?")
        params.append(user_id)
    sql = f"SELECT run_id, project_id, timestamp, runtime_seconds, active_runtime_seconds, color_preview, name, version_date, custom_metrics, thumb_label FROM runs WHERE {' AND '.join(conditions)} ORDER BY timestamp DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return query_all(sql, tuple(params))


def get_run_count_excluding_ids_query(run_ids, project_id=None, user_id=None):
    """Get count of runs excluding specific run IDs."""
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
    """Get total number of runs."""
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


# Filtered run queries for server-side pagination/sorting/filtering
_RUN_SORT_COLUMNS = {
    "timestamp",
    "run_id",
    "name",
    "version_date",
    "thumb_label",
    "runtime_seconds",
    "active_runtime_seconds",
}


def _normalize_timestamp_filter_value(value, end_of_range=False):
    """Normalize date/date-time filter values into SQLite timestamp strings."""
    normalized = str(value).strip().replace("T", " ")
    if len(normalized) == 10:
        return normalized + (" 23:59:59" if end_of_range else " 00:00:00")
    if len(normalized) == 16:
        return normalized + (":59" if end_of_range else ":00")
    return normalized


def _build_run_filters(filters):
    """Build WHERE conditions and params from a filter dict."""
    conditions = []
    params = []
    if filters.get("name"):
        conditions.append("LOWER(name) LIKE ?")
        params.append(f"%{filters['name'].lower()}%")
    if filters.get("run_id"):
        conditions.append("LOWER(run_id) LIKE ?")
        params.append(f"%{filters['run_id'].lower()}%")
    if filters.get("version_date"):
        values = filters["version_date"]
        placeholders = ",".join("?" * len(values))
        conditions.append(f"version_date IN ({placeholders})")
        params.extend(values)
    if filters.get("timestamp_from"):
        conditions.append("timestamp >= ?")
        params.append(_normalize_timestamp_filter_value(filters["timestamp_from"], end_of_range=False))
    if filters.get("timestamp_to"):
        conditions.append("timestamp <= ?")
        params.append(_normalize_timestamp_filter_value(filters["timestamp_to"], end_of_range=True))
    return conditions, params


def query_runs_filtered(project_id, exclude_ids, filters, sort_col, sort_dir, limit, offset, user_id=None):
    """Query runs with filtering, sorting, and pagination. Returns (rows, total_count)."""
    conditions = []
    params = []
    if project_id:
        conditions.append("project_id=?")
        params.append(project_id)
    if user_id:
        conditions.append("user_id=?")
        params.append(user_id)
    if exclude_ids:
        placeholders = ",".join("?" * len(exclude_ids))
        conditions.append(f"run_id NOT IN ({placeholders})")
        params.extend(exclude_ids)
    filter_conditions, filter_params = _build_run_filters(filters)
    conditions.extend(filter_conditions)
    params.extend(filter_params)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    if sort_col not in _RUN_SORT_COLUMNS:
        sort_col = "timestamp"
    sort_dir = "DESC" if sort_dir.upper() != "ASC" else "ASC"
    count_row = query_one(f"SELECT COUNT(*) as count FROM runs{where}", tuple(params))
    total = count_row["count"] if count_row else 0
    sql = f"SELECT run_id, project_id, timestamp, runtime_seconds, active_runtime_seconds, color_preview, name, version_date, custom_metrics, thumb_label FROM runs{where} ORDER BY {sort_col} {sort_dir}"
    data_params = list(params)
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        data_params.extend([limit, offset])
    rows = query_all(sql, tuple(data_params))
    return rows, total


def get_distinct_versions_query(project_id=None, user_id=None):
    """Get distinct version_date values for a project."""
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
    """Get detail fields for a single run."""
    return query_one(
        "SELECT run_id, project_id, name, timestamp, runtime_seconds, active_runtime_seconds, custom_metrics, thumb_label, notes, log, version_date FROM runs WHERE run_id=?",
        (run_id,),
    )


def get_run_graph_topology_query(run_id):
    """Get graph topology for an run."""
    return query_one("SELECT graph_topology FROM runs WHERE run_id=?", (run_id,))


def get_run_color_preview_query(run_id):
    """Get color preview for an run."""
    return query_one("SELECT color_preview FROM runs WHERE run_id=?", (run_id,))


def get_run_environment_query(parent_run_id):
    """Get run cwd, command, and environment."""
    return query_one(
        "SELECT cwd, command, environment FROM runs WHERE run_id=?", (parent_run_id,)
    )


def update_run_color_preview_query(color_preview_json, run_id):
    """Update run color preview."""
    execute(
        "UPDATE runs SET color_preview=? WHERE run_id=?",
        (color_preview_json, run_id),
    )


def get_run_exec_info_query(run_id):
    """Get run execution info (cwd, command, environment)."""
    return query_one(
        "SELECT cwd, command, environment FROM runs WHERE run_id=?", (run_id,)
    )


# Copy queries
def copy_llm_calls_query(old_run_id, new_run_id):
    """Copy all llm_calls from one run to another with a new run_id."""
    execute(
        """
        INSERT INTO llm_calls (run_id, node_uuid, input, input_hash, input_overwrite, output, color, label, api_type, stack_trace, timestamp)
        SELECT ?, node_uuid, input, input_hash, input_overwrite, output, color, label, api_type, stack_trace, timestamp
        FROM llm_calls WHERE run_id=?
        """,
        (new_run_id, old_run_id),
    )


# Database cleanup queries
def delete_all_runs_query():
    """Delete all records from runs table."""
    execute("DELETE FROM run_tags")
    execute("DELETE FROM runs")


def delete_all_llm_calls_query():
    """Delete all records from llm_calls table."""
    execute("DELETE FROM llm_calls")


def _delete_runs_data(run_ids):
    """Delete llm_calls, priors_applied, and runs for the given run IDs."""
    if not run_ids:
        return
    placeholders = ",".join("?" * len(run_ids))
    ids = tuple(run_ids)
    execute(f"DELETE FROM run_tags WHERE run_id IN ({placeholders})", ids)
    execute(f"DELETE FROM llm_calls WHERE run_id IN ({placeholders})", ids)
    execute(f"DELETE FROM priors_applied WHERE run_id IN ({placeholders})", ids)
    execute(f"DELETE FROM runs WHERE run_id IN ({placeholders})", ids)


def delete_runs_by_ids_query(run_ids, user_id=None):
    """Delete runs by run ID, optionally scoped to a user. Returns deleted count."""
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
        f"SELECT DISTINCT project_id FROM runs WHERE run_id IN ({placeholders}) AND project_id IS NOT NULL",
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


def delete_project_query(project_id):
    """Delete a project and all associated runs, llm_calls, priors_applied, and locations."""
    runs = query_all("SELECT run_id FROM runs WHERE project_id=?", (project_id,))
    _delete_runs_data([run["run_id"] for run in runs])
    execute("DELETE FROM project_tags WHERE project_id=?", (project_id,))
    execute("DELETE FROM user_project_locations WHERE project_id=?", (project_id,))
    execute("DELETE FROM projects WHERE project_id=?", (project_id,))


def delete_user_query(user_id):
    """Delete a user and all associated runs, llm_calls, priors_applied, and locations."""
    # 1. Get projects associated to this user
    project_ids = [
        r["project_id"]
        for r in query_all(
            "SELECT DISTINCT project_id FROM user_project_locations WHERE user_id=?", (user_id,)
        )
    ]
    # 2. For each project, get the set of all users belonging to it
    project_users: dict[str, set[str]] = {}
    for pid in project_ids:
        rows = query_all(
            "SELECT DISTINCT user_id FROM user_project_locations WHERE project_id=?", (pid,)
        )
        project_users[pid] = {r["user_id"] for r in rows}
    # Delete projects where this user is the sole member
    for pid, users in project_users.items():
        if users == {user_id}:
            delete_project_query(pid)
    runs = query_all("SELECT run_id FROM runs WHERE user_id=?", (user_id,))
    _delete_runs_data([run["run_id"] for run in runs])
    execute("DELETE FROM user_project_locations WHERE user_id=?", (user_id,))
    execute("DELETE FROM users WHERE user_id=?", (user_id,))


def get_run_name_query(run_id):
    """Get run name by run_id."""
    return query_one("SELECT name FROM runs WHERE run_id=?", (run_id,))


def find_run_ids_by_prefix_query(run_id_prefix):
    """Find run IDs matching a UUID prefix, ignoring hyphens and case."""
    return query_all(
        """
        SELECT run_id
        FROM runs
        WHERE REPLACE(LOWER(run_id), '-', '') LIKE ?
        ORDER BY timestamp DESC
        """,
        (f"{run_id_prefix.lower()}%",),
    )


def find_node_uuids_by_prefix_query(run_id, node_uuid_prefix):
    """Find node UUIDs in a run matching a UUID prefix, ignoring hyphens and case."""
    return query_all(
        """
        SELECT node_uuid
        FROM llm_calls
        WHERE run_id=? AND REPLACE(LOWER(node_uuid), '-', '') LIKE ?
        ORDER BY rowid
        """,
        (run_id, f"{node_uuid_prefix.lower()}%",),
    )


def get_llm_call_input_api_type_query(run_id, node_uuid):
    """Get input and api_type from llm_calls by run_id and node_uuid."""
    return query_one(
        "SELECT input, api_type FROM llm_calls WHERE run_id=? AND node_uuid=?",
        (run_id, node_uuid),
    )


def get_llm_call_output_api_type_query(run_id, node_uuid):
    """Get output and api_type from llm_calls by run_id and node_uuid."""
    return query_one(
        "SELECT output, api_type FROM llm_calls WHERE run_id=? AND node_uuid=?",
        (run_id, node_uuid),
    )


def get_run_log_success_graph_query(run_id):
    """Get log and graph_topology from runs by run_id."""
    return query_one(
        "SELECT log, graph_topology FROM runs WHERE run_id=?",
        (run_id,),
    )


def get_next_run_index_query(project_id=None, user_id=None):
    """Get the next run index based on how many runs already exist."""
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


# Probe-related queries for so-cli
def get_run_metadata_query(run_id):
    """Get run metadata for probe command."""
    return query_one(
        """SELECT run_id, parent_run_id, name, timestamp, custom_metrics, thumb_label, notes, log,
                  graph_topology, version_date
           FROM runs WHERE run_id=?""",
        (run_id,),
    )


def get_llm_calls_for_run_query(run_id):
    """Get all LLM calls for a run, ordered by insertion time."""
    return query_all(
        """SELECT node_uuid, input, input_overwrite, output, api_type, label, timestamp
           FROM llm_calls WHERE run_id=? ORDER BY rowid""",
        (run_id,),
    )


def get_llm_call_full_query(run_id, node_uuid):
    """Get full LLM call data including input, output, overwrites, and stack_trace."""
    return query_one(
        """SELECT node_uuid, input, input_hash, input_overwrite, output, api_type, label, timestamp, stack_trace
           FROM llm_calls WHERE run_id=? AND node_uuid=?""",
        (run_id, node_uuid),
    )
# ============================================================
# Priors queries
# ============================================================


# ============================================================
# Priors Applied queries
# ============================================================


def get_priors_applied_for_run_query(run_id):
    """Get prior application records for a specific run."""
    return query_all(
        """
        SELECT pa.prior_id, pa.run_id, pa.node_uuid, e.name as name
        FROM priors_applied pa
        LEFT JOIN runs e ON pa.run_id = e.run_id
        WHERE pa.run_id = ?
        ORDER BY pa.applied_at DESC
        """,
        (run_id,),
    )


def get_priors_applied_query(prior_id):
    """Get all runs/nodes where a specific prior was applied."""
    return query_all(
        """
        SELECT pa.run_id, pa.node_uuid, e.name as name
        FROM priors_applied pa
        LEFT JOIN runs e ON pa.run_id = e.run_id
        WHERE pa.prior_id = ?
        ORDER BY pa.applied_at DESC
        """,
        (prior_id,),
    )


def add_prior_applied_query(prior_id, run_id, node_uuid=None):
    """Record that a prior was applied to a run/node."""
    execute(
        """
        INSERT OR IGNORE INTO priors_applied (prior_id, run_id, node_uuid)
        VALUES (?, ?, ?)
        """,
        (prior_id, run_id, node_uuid),
    )


def remove_prior_applied_query(prior_id, run_id, node_uuid=None):
    """Remove a prior application record."""
    if node_uuid:
        execute(
            "DELETE FROM priors_applied WHERE prior_id = ? AND run_id = ? AND node_uuid = ?",
            (prior_id, run_id, node_uuid),
        )
    else:
        execute(
            "DELETE FROM priors_applied WHERE prior_id = ? AND run_id = ? AND node_uuid IS NULL",
            (prior_id, run_id),
        )


def delete_priors_applied_for_prior_query(prior_id):
    """Delete all application records for a prior."""
    execute("DELETE FROM priors_applied WHERE prior_id = ?", (prior_id,))


# ============================================================
# Project queries
# ============================================================


def upsert_project_query(project_id, name, description):
    """Insert project if new, update name/description if existing."""
    execute(
        "INSERT OR IGNORE INTO projects (project_id, name, description) VALUES (?, ?, ?)",
        (project_id, name, description),
    )
    execute(
        "UPDATE projects SET name=?, description=? WHERE project_id=?",
        (name, description, project_id),
    )


def update_project_last_run_at_query(project_id):
    """Update project last_run_at to now."""
    execute(
        "UPDATE projects SET last_run_at=datetime('now') WHERE project_id=?",
        (project_id,),
    )


def get_project_query(project_id):
    """Get project by project_id."""
    return query_one(
        "SELECT project_id, name, description FROM projects WHERE project_id=?",
        (project_id,),
    )


def get_all_projects_query(user_id=None):
    """Get all projects ordered by last_run_at desc."""
    if user_id:
        return query_all(
            """SELECT DISTINCT p.project_id, p.name, p.description, p.created_at, p.last_run_at
               FROM projects p
               JOIN user_project_locations upl ON p.project_id = upl.project_id
               WHERE upl.user_id = ?
               ORDER BY p.last_run_at DESC""",
            (user_id,),
        )
    return query_all(
        "SELECT project_id, name, description, created_at, last_run_at FROM projects ORDER BY last_run_at DESC",
        (),
    )


def get_project_user_count_query(project_id):
    """Count distinct users who have this project registered."""
    row = query_one(
        "SELECT COUNT(DISTINCT user_id) as count FROM user_project_locations WHERE project_id=?",
        (project_id,),
    )
    return row["count"] if row else 0


# User-project location queries

def upsert_project_location_query(user_id, project_id, project_location):
    """Record that a user has a project at this location. Updates project_id if location already known."""
    execute(
        """INSERT INTO user_project_locations (user_id, project_id, project_location)
           VALUES (?, ?, ?)
           ON CONFLICT (user_id, project_location)
           DO UPDATE SET project_id=excluded.project_id""",
        (user_id, project_id, project_location),
    )


def get_project_at_location_query(user_id, project_location):
    """Find a project for this user whose known location is an ancestor of (or equal to) the given path."""
    rows = query_all(
        "SELECT project_id, project_location FROM user_project_locations WHERE user_id=?",
        (user_id,),
    )
    return rows


def get_project_locations_query(user_id, project_id):
    """Get all known locations for a project belonging to a user."""
    return query_all(
        "SELECT project_location FROM user_project_locations WHERE user_id=? AND project_id=?",
        (user_id, project_id),
    )


def get_all_project_locations_query(project_id):
    """Get all known locations for a project across all users."""
    return query_all(
        "SELECT project_location FROM user_project_locations WHERE project_id=?",
        (project_id,),
    )


def delete_project_location_query(user_id, project_id, project_location):
    """Delete a single project location row."""
    execute(
        "DELETE FROM user_project_locations WHERE user_id=? AND project_id=? AND project_location=?",
        (user_id, project_id, project_location),
    )
