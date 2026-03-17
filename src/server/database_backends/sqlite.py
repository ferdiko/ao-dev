"""
SQLite database backend for workflow experiments.

Uses per-thread connections via threading.local() so readers can run concurrently
under WAL mode. Writers still serialize at the SQLite level (WAL allows only one
writer at a time), but that's SQLite's own locking — not a Python bottleneck.
"""

import os
import sqlite3
import threading

from ao.common.logger import logger
from ao.common.constants import DB_PATH


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

    db_path = os.path.join(DB_PATH, "experiments.sqlite")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(
        db_path,
        timeout=30.0,
        detect_types=sqlite3.PARSE_DECLTYPES,
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
    logger.debug(f"Created per-thread DB connection at {db_path}")
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

    # Create experiments table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS experiments (
            session_id TEXT PRIMARY KEY,
            parent_session_id TEXT,
            project_id TEXT,
            user_id TEXT,
            graph_topology TEXT,
            color_preview TEXT,
            timestamp TIMESTAMP DEFAULT (datetime('now')),
            cwd TEXT,
            command TEXT,
            environment TEXT,
            version_date TEXT,
            name TEXT,
            success TEXT CHECK (success IN ('', 'Satisfactory', 'Failed')),
            notes TEXT,
            log TEXT,
            FOREIGN KEY (parent_session_id) REFERENCES experiments (session_id),
            FOREIGN KEY (project_id) REFERENCES projects (project_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            UNIQUE (parent_session_id, name)
        )
    """
    )
    # Create llm_calls table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_calls (
            session_id TEXT,
            node_id TEXT,
            input TEXT,
            input_hash TEXT,
            input_overwrite TEXT,
            output TEXT,
            color TEXT,
            label TEXT,
            api_type TEXT,
            stack_trace TEXT,
            timestamp TIMESTAMP DEFAULT (datetime('now')),
            PRIMARY KEY (session_id, node_id),
            FOREIGN KEY (session_id) REFERENCES experiments (session_id)
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
        CREATE INDEX IF NOT EXISTS original_input_lookup ON llm_calls(session_id, input_hash)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS experiments_timestamp_idx ON experiments(timestamp DESC)
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS experiments_project_idx ON experiments(project_id, timestamp DESC)
    """
    )

    # Create lessons_applied table (tracks which lessons from ao-playbook were applied to runs)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS lessons_applied (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            node_id TEXT,
            applied_at TIMESTAMP DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES experiments (session_id),
            UNIQUE (lesson_id, session_id, node_id)
        )
    """
    )
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS lessons_applied_lesson_idx ON lessons_applied(lesson_id)
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


def add_experiment_query(
    session_id,
    parent_session_id,
    name,
    default_graph,
    timestamp,
    cwd,
    command,
    env_json,
    default_success,
    default_note,
    default_log,
    version_date,
    project_id=None,
    user_id=None,
):
    """Execute SQLite-specific INSERT for experiments table"""
    execute(
        "INSERT OR REPLACE INTO experiments (session_id, parent_session_id, project_id, user_id, name, graph_topology, timestamp, cwd, command, environment, version_date, success, notes, log) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            parent_session_id,
            project_id,
            user_id,
            name,
            default_graph,
            timestamp,
            cwd,
            command,
            env_json,
            version_date,
            default_success,
            default_note,
            default_log,
        ),
    )


def set_input_overwrite_query(input_overwrite, session_id, node_id):
    """Execute SQLite-specific UPDATE for llm_calls input_overwrite"""
    execute(
        "UPDATE llm_calls SET input_overwrite=?, output=NULL WHERE session_id=? AND node_id=?",
        (input_overwrite, session_id, node_id),
    )


def set_output_overwrite_query(output_overwrite, session_id, node_id):
    """Execute SQLite-specific UPDATE for llm_calls output"""
    execute(
        "UPDATE llm_calls SET output=? WHERE session_id=? AND node_id=?",
        (output_overwrite, session_id, node_id),
    )


def delete_llm_calls_query(session_id):
    """Execute SQLite-specific DELETE for llm_calls"""
    execute("DELETE FROM llm_calls WHERE session_id=?", (session_id,))


def update_experiment_graph_topology_query(graph_json, session_id):
    """Execute SQLite-specific UPDATE for experiments graph_topology"""
    execute("UPDATE experiments SET graph_topology=? WHERE session_id=?", (graph_json, session_id))


def update_experiment_timestamp_query(timestamp, session_id):
    """Execute SQLite-specific UPDATE for experiments timestamp"""
    execute("UPDATE experiments SET timestamp=? WHERE session_id=?", (timestamp, session_id))


def update_experiment_name_query(run_name, session_id):
    """Execute SQLite-specific UPDATE for experiments name"""
    execute(
        "UPDATE experiments SET name=? WHERE session_id=?",
        (run_name, session_id),
    )


def update_experiment_result_query(result, session_id):
    """Execute SQLite-specific UPDATE for experiments success"""
    execute(
        "UPDATE experiments SET success=? WHERE session_id=?",
        (result, session_id),
    )


def update_experiment_notes_query(notes, session_id):
    """Execute SQLite-specific UPDATE for experiments notes"""
    execute(
        "UPDATE experiments SET notes=? WHERE session_id=?",
        (notes, session_id),
    )


def update_experiment_command_query(command, session_id):
    """Execute SQLite-specific UPDATE for experiments command"""
    execute(
        "UPDATE experiments SET command=? WHERE session_id=?",
        (command, session_id),
    )


def update_experiment_version_date_query(version_date, session_id):
    """Execute SQLite-specific UPDATE for experiments version_date"""
    execute(
        "UPDATE experiments SET version_date=? WHERE session_id=?",
        (version_date, session_id),
    )


def update_experiment_log_query(
    updated_log, updated_success, color_preview_json, graph_json, session_id
):
    """Execute SQLite-specific UPDATE for experiments log, success, color_preview, and graph_topology"""
    execute(
        "UPDATE experiments SET log=?, success=?, color_preview=?, graph_topology=? WHERE session_id=?",
        (updated_log, updated_success, color_preview_json, graph_json, session_id),
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
def get_subrun_by_parent_and_name_query(parent_session_id, name):
    """Get subrun session_id by parent session and name."""
    return query_one(
        "SELECT session_id FROM experiments WHERE parent_session_id = ? AND name = ?",
        (parent_session_id, name),
    )


def get_parent_session_id_query(session_id):
    """Get parent session ID for a given session."""
    return query_one("SELECT parent_session_id FROM experiments WHERE session_id=?", (session_id,))


# LLM calls queries
def get_llm_call_by_session_and_hash_query(session_id, input_hash):
    """Get LLM call by session_id and input_hash."""
    return query_one(
        "SELECT node_id, input_overwrite, output FROM llm_calls WHERE session_id=? AND input_hash=?",
        (session_id, input_hash),
    )


def insert_llm_call_with_output_query(
    session_id, input_pickle, input_hash, node_id, api_type, output_pickle, stack_trace=None
):
    """Insert new LLM call record with output in a single operation (upsert)."""
    execute(
        """
        INSERT INTO llm_calls (session_id, input, input_hash, node_id, api_type, output, stack_trace)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (session_id, node_id)
        DO UPDATE SET output = excluded.output, stack_trace = excluded.stack_trace
        """,
        (session_id, input_pickle, input_hash, node_id, api_type, output_pickle, stack_trace),
    )


# Experiment list and graph queries
def get_finished_runs_query(project_id=None):
    """Get all finished runs ordered by timestamp."""
    if project_id:
        return query_all(
            "SELECT session_id, timestamp FROM experiments WHERE project_id=? ORDER BY timestamp DESC",
            (project_id,),
        )
    return query_all("SELECT session_id, timestamp FROM experiments ORDER BY timestamp DESC", ())


def get_all_experiments_sorted_query(limit=None, offset=0, project_id=None):
    """Get experiments sorted by timestamp desc, with optional pagination."""
    base = "SELECT session_id, timestamp, color_preview, name, version_date, success FROM experiments"
    params = []
    if project_id:
        base += " WHERE project_id=?"
        params.append(project_id)
    base += " ORDER BY timestamp DESC"
    if limit is not None:
        base += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return query_all(base, tuple(params))


def get_experiments_by_ids_query(session_ids, project_id=None):
    """Get experiments for specific session IDs, sorted by timestamp desc."""
    if not session_ids:
        return []
    placeholders = ",".join("?" * len(session_ids))
    params = list(session_ids)
    sql = f"SELECT session_id, timestamp, color_preview, name, version_date, success FROM experiments WHERE session_id IN ({placeholders})"
    if project_id:
        sql += " AND project_id=?"
        params.append(project_id)
    sql += " ORDER BY timestamp DESC"
    return query_all(sql, tuple(params))


def get_experiments_excluding_ids_query(session_ids, limit=None, offset=0, project_id=None):
    """Get experiments excluding specific session IDs, sorted by timestamp desc."""
    if not session_ids:
        return get_all_experiments_sorted_query(limit=limit, offset=offset, project_id=project_id)
    placeholders = ",".join("?" * len(session_ids))
    params = list(session_ids)
    conditions = [f"session_id NOT IN ({placeholders})"]
    if project_id:
        conditions.append("project_id=?")
        params.append(project_id)
    sql = f"SELECT session_id, timestamp, color_preview, name, version_date, success FROM experiments WHERE {' AND '.join(conditions)} ORDER BY timestamp DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return query_all(sql, tuple(params))


def get_experiment_count_excluding_ids_query(session_ids, project_id=None):
    """Get count of experiments excluding specific session IDs."""
    if not session_ids:
        return get_experiment_count_query(project_id=project_id)
    placeholders = ",".join("?" * len(session_ids))
    params = list(session_ids)
    conditions = [f"session_id NOT IN ({placeholders})"]
    if project_id:
        conditions.append("project_id=?")
        params.append(project_id)
    row = query_one(
        f"SELECT COUNT(*) as count FROM experiments WHERE {' AND '.join(conditions)}",
        tuple(params),
    )
    return row["count"] if row else 0


def get_experiment_count_query(project_id=None):
    """Get total number of experiments."""
    if project_id:
        row = query_one("SELECT COUNT(*) as count FROM experiments WHERE project_id=?", (project_id,))
    else:
        row = query_one("SELECT COUNT(*) as count FROM experiments", ())
    return row["count"] if row else 0


def get_experiment_detail_query(session_id):
    """Get notes and log for a single experiment."""
    return query_one(
        "SELECT notes, log FROM experiments WHERE session_id=?",
        (session_id,),
    )


def get_experiment_graph_topology_query(session_id):
    """Get graph topology for an experiment."""
    return query_one("SELECT graph_topology FROM experiments WHERE session_id=?", (session_id,))


def get_experiment_color_preview_query(session_id):
    """Get color preview for an experiment."""
    return query_one("SELECT color_preview FROM experiments WHERE session_id=?", (session_id,))


def get_experiment_environment_query(parent_session_id):
    """Get experiment cwd, command, and environment."""
    return query_one(
        "SELECT cwd, command, environment FROM experiments WHERE session_id=?", (parent_session_id,)
    )


def update_experiment_color_preview_query(color_preview_json, session_id):
    """Update experiment color preview."""
    execute(
        "UPDATE experiments SET color_preview=? WHERE session_id=?",
        (color_preview_json, session_id),
    )


def get_experiment_exec_info_query(session_id):
    """Get experiment execution info (cwd, command, environment)."""
    return query_one(
        "SELECT cwd, command, environment FROM experiments WHERE session_id=?", (session_id,)
    )


# Copy queries
def copy_llm_calls_query(old_session_id, new_session_id):
    """Copy all llm_calls from one session to another with a new session_id."""
    execute(
        """
        INSERT INTO llm_calls (session_id, node_id, input, input_hash, input_overwrite, output, color, label, api_type, stack_trace, timestamp)
        SELECT ?, node_id, input, input_hash, input_overwrite, output, color, label, api_type, stack_trace, timestamp
        FROM llm_calls WHERE session_id=?
        """,
        (new_session_id, old_session_id),
    )


# Database cleanup queries
def delete_all_experiments_query():
    """Delete all records from experiments table."""
    execute("DELETE FROM experiments")


def delete_all_llm_calls_query():
    """Delete all records from llm_calls table."""
    execute("DELETE FROM llm_calls")


def get_session_name_query(session_id):
    """Get session name by session_id."""
    return query_one("SELECT name FROM experiments WHERE session_id=?", (session_id,))


def get_llm_call_input_api_type_query(session_id, node_id):
    """Get input and api_type from llm_calls by session_id and node_id."""
    return query_one(
        "SELECT input, api_type FROM llm_calls WHERE session_id=? AND node_id=?",
        (session_id, node_id),
    )


def get_llm_call_output_api_type_query(session_id, node_id):
    """Get output and api_type from llm_calls by session_id and node_id."""
    return query_one(
        "SELECT output, api_type FROM llm_calls WHERE session_id=? AND node_id=?",
        (session_id, node_id),
    )


def get_experiment_log_success_graph_query(session_id):
    """Get log, success, and graph_topology from experiments by session_id."""
    return query_one(
        "SELECT log, success, graph_topology FROM experiments WHERE session_id=?",
        (session_id,),
    )


def get_next_run_index_query(project_id=None):
    """Get the next run index based on how many runs already exist."""
    if project_id:
        row = query_one("SELECT COUNT(*) as count FROM experiments WHERE project_id=?", (project_id,))
    else:
        row = query_one("SELECT COUNT(*) as count FROM experiments", ())
    if row:
        return row["count"] + 1
    return 1


# Probe-related queries for ao-tool
def get_experiment_metadata_query(session_id):
    """Get experiment metadata for probe command."""
    return query_one(
        """SELECT session_id, parent_session_id, name, timestamp, success, notes, log,
                  graph_topology, version_date
           FROM experiments WHERE session_id=?""",
        (session_id,),
    )


def get_llm_calls_for_session_query(session_id):
    """Get all LLM calls for a session."""
    return query_all(
        """SELECT node_id, input, input_overwrite, output, api_type, label, timestamp
           FROM llm_calls WHERE session_id=?""",
        (session_id,),
    )


def get_llm_call_full_query(session_id, node_id):
    """Get full LLM call data including input, output, overwrites, and stack_trace."""
    return query_one(
        """SELECT node_id, input, input_hash, input_overwrite, output, api_type, label, timestamp, stack_trace
           FROM llm_calls WHERE session_id=? AND node_id=?""",
        (session_id, node_id),
    )
# ============================================================
# Lessons queries
# ============================================================


# ============================================================
# Lessons Applied queries (tracks which ao-playbook lessons were applied to runs)
# ============================================================


def get_all_lessons_applied_query():
    """Get all lesson application records with run names for merging with ao-playbook data."""
    return query_all(
        """
        SELECT la.lesson_id, la.session_id, la.node_id, e.name as run_name
        FROM lessons_applied la
        LEFT JOIN experiments e ON la.session_id = e.session_id
        ORDER BY la.applied_at DESC
        """,
        (),
    )


def get_lessons_applied_query(lesson_id):
    """Get all sessions/nodes where a specific lesson was applied."""
    return query_all(
        """
        SELECT la.session_id, la.node_id, e.name as run_name
        FROM lessons_applied la
        LEFT JOIN experiments e ON la.session_id = e.session_id
        WHERE la.lesson_id = ?
        ORDER BY la.applied_at DESC
        """,
        (lesson_id,),
    )


def add_lesson_applied_query(lesson_id, session_id, node_id=None):
    """Record that a lesson was applied to a session/node."""
    execute(
        """
        INSERT OR IGNORE INTO lessons_applied (lesson_id, session_id, node_id)
        VALUES (?, ?, ?)
        """,
        (lesson_id, session_id, node_id),
    )


def remove_lesson_applied_query(lesson_id, session_id, node_id=None):
    """Remove a lesson application record."""
    if node_id:
        execute(
            "DELETE FROM lessons_applied WHERE lesson_id = ? AND session_id = ? AND node_id = ?",
            (lesson_id, session_id, node_id),
        )
    else:
        execute(
            "DELETE FROM lessons_applied WHERE lesson_id = ? AND session_id = ? AND node_id IS NULL",
            (lesson_id, session_id),
        )


def delete_lessons_applied_for_lesson_query(lesson_id):
    """Delete all application records for a lesson (when lesson is deleted from ao-playbook)."""
    execute("DELETE FROM lessons_applied WHERE lesson_id = ?", (lesson_id,))


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


def get_all_projects_query():
    """Get all projects ordered by last_run_at desc."""
    return query_all(
        "SELECT project_id, name, description, created_at, last_run_at FROM projects ORDER BY last_run_at DESC",
        (),
    )
