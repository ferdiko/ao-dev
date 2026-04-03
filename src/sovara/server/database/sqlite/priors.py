from .connection import execute, query_all


def get_priors_applied_for_run_query(run_id):
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
    execute(
        """
        INSERT OR IGNORE INTO priors_applied (prior_id, run_id, node_uuid)
        VALUES (?, ?, ?)
        """,
        (prior_id, run_id, node_uuid),
    )


def remove_prior_applied_query(prior_id, run_id, node_uuid=None):
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
    execute("DELETE FROM priors_applied WHERE prior_id = ?", (prior_id,))
