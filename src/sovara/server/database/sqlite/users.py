from .connection import execute, query_all, query_one


def upsert_user_query(user_id, full_name, email):
    execute(
        "INSERT OR IGNORE INTO users (user_id, full_name, email) VALUES (?, ?, ?)",
        (user_id, full_name, email),
    )
    execute(
        "UPDATE users SET full_name=?, email=? WHERE user_id=?",
        (full_name, email, user_id),
    )


def get_user_query(user_id):
    return query_one(
        """
        SELECT
            user_id,
            full_name,
            email,
            llm_primary_provider,
            llm_primary_model_name,
            llm_primary_api_base,
            llm_helper_provider,
            llm_helper_model_name,
            llm_helper_api_base
        FROM users
        WHERE user_id=?
        """,
        (user_id,),
    )


def update_user_llm_settings_query(user_id, llm_settings):
    execute(
        """
        UPDATE users
        SET llm_primary_provider=?,
            llm_primary_model_name=?,
            llm_primary_api_base=?,
            llm_helper_provider=?,
            llm_helper_model_name=?,
            llm_helper_api_base=?
        WHERE user_id=?
        """,
        (
            llm_settings["llm_primary_provider"],
            llm_settings["llm_primary_model_name"],
            llm_settings["llm_primary_api_base"],
            llm_settings["llm_helper_provider"],
            llm_settings["llm_helper_model_name"],
            llm_settings["llm_helper_api_base"],
            user_id,
        ),
    )


def delete_user_query(user_id):
    from .projects import delete_project_query
    from .runs import _delete_runs_data

    project_ids = [
        row["project_id"]
        for row in query_all(
            "SELECT DISTINCT project_id FROM user_project_locations WHERE user_id=?",
            (user_id,),
        )
    ]
    project_users: dict[str, set[str]] = {}
    for project_id in project_ids:
        rows = query_all(
            "SELECT DISTINCT user_id FROM user_project_locations WHERE project_id=?",
            (project_id,),
        )
        project_users[project_id] = {row["user_id"] for row in rows}
    for project_id, users in project_users.items():
        if users == {user_id}:
            delete_project_query(project_id)

    runs = query_all("SELECT run_id FROM runs WHERE user_id=?", (user_id,))
    _delete_runs_data([run["run_id"] for run in runs])
    execute("DELETE FROM user_project_locations WHERE user_id=?", (user_id,))
    execute("DELETE FROM users WHERE user_id=?", (user_id,))
