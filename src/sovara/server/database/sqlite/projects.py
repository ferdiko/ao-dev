from .connection import execute, get_conn, query_all, query_one


def get_project_tags_query(project_id):
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
    return query_one(
        """
        SELECT tag_id, project_id, name, color, created_at
        FROM project_tags
        WHERE tag_id=?
        """,
        (tag_id,),
    )


def get_project_tag_by_name_query(project_id, name):
    return query_one(
        """
        SELECT tag_id, project_id, name, color, created_at
        FROM project_tags
        WHERE project_id=? AND name=?
        """,
        (project_id, name),
    )


def get_project_tags_by_ids_query(project_id, tag_ids):
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
    execute(
        """
        INSERT INTO project_tags (tag_id, project_id, name, color)
        VALUES (?, ?, ?, ?)
        """,
        (tag_id, project_id, name, color),
    )


def delete_project_tag_query(project_id, tag_id):
    execute("DELETE FROM run_tags WHERE tag_id=?", (tag_id,))
    execute("DELETE FROM project_tags WHERE project_id=? AND tag_id=?", (project_id, tag_id))


def get_tags_for_runs_query(run_ids):
    if not run_ids:
        return []
    placeholders = ",".join("?" * len(run_ids))
    return query_all(
        f"""
        SELECT rt.run_id, pt.tag_id, pt.project_id, pt.name, pt.color, pt.created_at
        FROM run_tags rt
        JOIN project_tags pt ON pt.tag_id = rt.tag_id
        WHERE rt.run_id IN ({placeholders})
        ORDER BY LOWER(pt.name) ASC, pt.tag_id ASC
        """,
        tuple(run_ids),
    )


def replace_run_tags_query(run_id, tag_ids):
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
    return query_all(
        """
        SELECT metric_key, metric_kind
        FROM project_metric_kinds
        WHERE project_id=?
        ORDER BY metric_key ASC
        """,
        (project_id,),
    )


def upsert_project_metric_kind_query(project_id, metric_key, metric_kind):
    execute(
        """
        INSERT INTO project_metric_kinds (project_id, metric_key, metric_kind)
        VALUES (?, ?, ?)
        ON CONFLICT(project_id, metric_key) DO UPDATE SET metric_kind=excluded.metric_kind
        """,
        (project_id, metric_key, metric_kind),
    )


def upsert_project_query(project_id, name, description):
    execute(
        "INSERT OR IGNORE INTO projects (project_id, name, description) VALUES (?, ?, ?)",
        (project_id, name, description),
    )
    execute(
        "UPDATE projects SET name=?, description=? WHERE project_id=?",
        (name, description, project_id),
    )


def update_project_last_run_at_query(project_id):
    execute(
        "UPDATE projects SET last_run_at=datetime('now') WHERE project_id=?",
        (project_id,),
    )


def get_project_query(project_id):
    return query_one(
        "SELECT project_id, name, description FROM projects WHERE project_id=?",
        (project_id,),
    )


def get_all_projects_query(user_id=None):
    if user_id:
        return query_all(
            """
            SELECT DISTINCT p.project_id, p.name, p.description, p.created_at, p.last_run_at
            FROM projects p
            JOIN user_project_locations upl ON p.project_id = upl.project_id
            WHERE upl.user_id = ?
            ORDER BY p.last_run_at DESC
            """,
            (user_id,),
        )
    return query_all(
        """
        SELECT project_id, name, description, created_at, last_run_at
        FROM projects
        ORDER BY last_run_at DESC
        """,
        (),
    )


def get_project_user_count_query(project_id):
    row = query_one(
        "SELECT COUNT(DISTINCT user_id) as count FROM user_project_locations WHERE project_id=?",
        (project_id,),
    )
    return row["count"] if row else 0


def delete_project_query(project_id):
    from .runs import _delete_runs_data

    runs = query_all("SELECT run_id FROM runs WHERE project_id=?", (project_id,))
    _delete_runs_data([run["run_id"] for run in runs])
    execute("DELETE FROM project_tags WHERE project_id=?", (project_id,))
    execute("DELETE FROM user_project_locations WHERE project_id=?", (project_id,))
    execute("DELETE FROM projects WHERE project_id=?", (project_id,))


def upsert_project_location_query(user_id, project_id, project_location):
    execute(
        """
        INSERT INTO user_project_locations (user_id, project_id, project_location)
        VALUES (?, ?, ?)
        ON CONFLICT (user_id, project_location)
        DO UPDATE SET project_id=excluded.project_id
        """,
        (user_id, project_id, project_location),
    )


def get_project_at_location_query(user_id, project_location):
    return query_all(
        "SELECT project_id, project_location FROM user_project_locations WHERE user_id=?",
        (user_id,),
    )


def get_project_locations_query(user_id, project_id):
    return query_all(
        "SELECT project_location FROM user_project_locations WHERE user_id=? AND project_id=?",
        (user_id, project_id),
    )


def get_all_project_locations_query(project_id):
    return query_all(
        "SELECT project_location FROM user_project_locations WHERE project_id=?",
        (project_id,),
    )


def delete_project_location_query(user_id, project_id, project_location):
    execute(
        "DELETE FROM user_project_locations WHERE user_id=? AND project_id=? AND project_location=?",
        (user_id, project_id, project_location),
    )
