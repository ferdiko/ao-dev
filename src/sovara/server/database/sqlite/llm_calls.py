from .connection import execute, query_all, query_one


def set_input_overwrite_query(input_overwrite, run_id, node_uuid):
    execute(
        "UPDATE llm_calls SET input_overwrite=?, output=NULL WHERE run_id=? AND node_uuid=?",
        (input_overwrite, run_id, node_uuid),
    )


def set_output_overwrite_query(output_overwrite, run_id, node_uuid):
    execute(
        "UPDATE llm_calls SET output=? WHERE run_id=? AND node_uuid=?",
        (output_overwrite, run_id, node_uuid),
    )


def delete_llm_calls_query(run_id):
    execute("DELETE FROM llm_calls WHERE run_id=?", (run_id,))


def check_attachment_exists_query(file_id):
    return query_one("SELECT file_id FROM attachments WHERE file_id=?", (file_id,))


def get_attachment_by_content_hash_query(content_hash):
    return query_one("SELECT file_path FROM attachments WHERE content_hash=?", (content_hash,))


def insert_attachment_query(file_id, content_hash, file_path):
    execute(
        "INSERT INTO attachments (file_id, content_hash, file_path) VALUES (?, ?, ?)",
        (file_id, content_hash, file_path),
    )


def get_attachment_file_path_query(file_id):
    return query_one("SELECT file_path FROM attachments WHERE file_id=?", (file_id,))


def get_subrun_by_parent_and_name_query(parent_run_id, name):
    return query_one(
        "SELECT run_id FROM runs WHERE parent_run_id = ? AND name = ?",
        (parent_run_id, name),
    )


def get_parent_run_id_query(run_id):
    return query_one("SELECT parent_run_id FROM runs WHERE run_id=?", (run_id,))


def get_llm_call_by_run_and_hash_query(run_id, input_hash, offset=0):
    return query_one(
        """
        SELECT node_uuid, input_overwrite, output
        FROM llm_calls
        WHERE run_id=? AND input_hash=?
        ORDER BY rowid
        LIMIT 1 OFFSET ?
        """,
        (run_id, input_hash, offset),
    )


def insert_llm_call_with_output_query(
    run_id, input_pickle, input_hash, node_uuid, api_type, output_pickle, stack_trace=None
):
    execute(
        """
        INSERT INTO llm_calls (run_id, input, input_hash, node_uuid, api_type, output, stack_trace)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (run_id, node_uuid)
        DO UPDATE SET output = excluded.output, stack_trace = excluded.stack_trace
        """,
        (run_id, input_pickle, input_hash, node_uuid, api_type, output_pickle, stack_trace),
    )


def copy_llm_calls_query(old_run_id, new_run_id):
    execute(
        """
        INSERT INTO llm_calls (
            run_id,
            node_uuid,
            input,
            input_hash,
            input_overwrite,
            output,
            color,
            label,
            api_type,
            stack_trace,
            timestamp
        )
        SELECT ?, node_uuid, input, input_hash, input_overwrite, output, color, label, api_type,
               stack_trace, timestamp
        FROM llm_calls WHERE run_id=?
        """,
        (new_run_id, old_run_id),
    )


def delete_all_llm_calls_query():
    execute("DELETE FROM llm_calls")


def find_node_uuids_by_prefix_query(run_id, node_uuid_prefix):
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
    return query_one(
        "SELECT input, api_type FROM llm_calls WHERE run_id=? AND node_uuid=?",
        (run_id, node_uuid),
    )


def get_llm_call_output_api_type_query(run_id, node_uuid):
    return query_one(
        "SELECT output, api_type FROM llm_calls WHERE run_id=? AND node_uuid=?",
        (run_id, node_uuid),
    )


def get_llm_calls_for_run_query(run_id):
    return query_all(
        """
        SELECT node_uuid, input, input_overwrite, output, api_type, label, timestamp
        FROM llm_calls
        WHERE run_id=?
        ORDER BY rowid
        """,
        (run_id,),
    )


def get_llm_call_full_query(run_id, node_uuid):
    return query_one(
        """
        SELECT node_uuid, input, input_hash, input_overwrite, output, api_type, label, timestamp,
               stack_trace
        FROM llm_calls
        WHERE run_id=? AND node_uuid=?
        """,
        (run_id, node_uuid),
    )
