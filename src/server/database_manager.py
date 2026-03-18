"""
Database manager for experiment and LLM call data.

This module provides a unified interface for database operations using SQLite.
"""

import time
import uuid
import json
import random
from dataclasses import dataclass
from typing import Optional, Any

from ao.common.logger import logger

from ao.runner.monkey_patching.api_parser import (
    func_kwargs_to_json_str,
    json_str_to_api_obj,
    api_obj_to_json_str,
    json_str_to_original_inp_dict,
    api_obj_to_response_ok,
)


@dataclass
class CacheOutput:
    """
    Encapsulates the output of cache operations for LLM calls.

    This dataclass stores all the necessary information returned by cache lookups
    and used for cache storage operations.

    Attributes:
        input_dict: The (potentially modified) input dictionary for the LLM call
        output: The cached output object, None if not cached or cache miss
        node_id: Unique identifier for this LLM call node, None if new call
        input_pickle: Serialized input data for caching purposes
        input_hash: Hash of the input for efficient cache lookups
        session_id: The session ID associated with this cache operation
        stack_trace: Python stack trace at the point of the LLM call
    """

    input_dict: dict
    output: Optional[Any]
    node_id: Optional[str]
    input_pickle: bytes
    input_hash: str
    session_id: str
    stack_trace: Optional[str] = None


class DatabaseManager:
    """Manages database operations using SQLite backend."""

    def __init__(self):
        from ao.common.constants import ATTACHMENT_CACHE

        self.cache_attachments = True
        self.attachment_cache_dir = ATTACHMENT_CACHE

    @property
    def backend(self):
        """Return the SQLite backend module (lazy-loaded)."""
        if not hasattr(self, "_backend_module"):
            from ao.server.database_backends import sqlite

            self._backend_module = sqlite
        return self._backend_module

    # Low-level database operations
    def query_one(self, query, params=None):
        return self.backend.query_one(query, params or ())

    def query_all(self, query, params=None):
        return self.backend.query_all(query, params or ())

    def execute(self, query, params=None):
        return self.backend.execute(query, params or ())

    def set_input_overwrite(self, session_id, node_id, new_input):
        # Normalize JSON representation
        new_input = json.dumps(json.loads(new_input), sort_keys=True)
        row = self.backend.get_llm_call_input_api_type_query(session_id, node_id)
        original_input = json.dumps(json.loads(row["input"]), sort_keys=True)
        # Only clear output if input actually changed
        if original_input != new_input:
            self.backend.set_input_overwrite_query(new_input, session_id, node_id)

    def set_output_overwrite(self, session_id, node_id, new_output: str):
        row = self.backend.get_llm_call_output_api_type_query(session_id, node_id)

        if not row:
            logger.error(
                f"No llm_calls record found for session_id={session_id}, node_id={node_id}"
            )
            return

        try:
            json_str_to_api_obj(new_output, row["api_type"])
            new_output = json.dumps(json.loads(new_output), sort_keys=True)
            self.backend.set_output_overwrite_query(new_output, session_id, node_id)
        except Exception as e:
            logger.error(f"Failed to parse output edit into API object: {e}")

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
        from ao.common.constants import DEFAULT_LOG, DEFAULT_NOTE, DEFAULT_SUCCESS

        default_graph = json.dumps({"nodes": [], "edges": []})
        parent_session_id = parent_session_id if parent_session_id else session_id
        env_json = json.dumps(environment)

        self.backend.add_experiment_query(
            session_id,
            parent_session_id,
            name,
            default_graph,
            timestamp,
            cwd,
            command,
            env_json,
            DEFAULT_SUCCESS,
            DEFAULT_NOTE,
            DEFAULT_LOG,
            version_date,
            project_id,
            user_id,
        )

    def update_graph_topology(self, session_id, graph_dict):
        graph_json = json.dumps(graph_dict)
        self.backend.update_experiment_graph_topology_query(graph_json, session_id)

    def update_timestamp(self, session_id, timestamp):
        self.backend.update_experiment_timestamp_query(timestamp, session_id)

    def update_run_name(self, session_id, run_name):
        self.backend.update_experiment_name_query(run_name, session_id)

    def update_result(self, session_id, result):
        self.backend.update_experiment_result_query(result, session_id)

    def update_notes(self, session_id, notes):
        self.backend.update_experiment_notes_query(notes, session_id)

    def update_command(self, session_id, command):
        self.backend.update_experiment_command_query(command, session_id)

    def update_experiment_version_date(self, session_id, version_date):
        self.backend.update_experiment_version_date_query(version_date, session_id)

    def _color_graph_nodes(self, graph, color):
        """Update border_color for each node."""
        for node in graph.get("nodes", []):
            node["border_color"] = color

        color_preview = [color for _ in graph.get("nodes", [])]
        return graph, color_preview

    def add_log(self, session_id, success, new_entry):
        """Write success and new_entry to DB under certain conditions."""
        from ao.common.constants import DEFAULT_LOG, SUCCESS_STRING, SUCCESS_COLORS

        row = self.backend.get_experiment_log_success_graph_query(session_id)

        existing_log = row["log"]
        existing_success = row["success"]
        graph = json.loads(row["graph_topology"])

        if new_entry is None:
            updated_log = existing_log
        elif existing_log == DEFAULT_LOG:
            updated_log = new_entry
        else:
            updated_log = existing_log + "\n" + new_entry

        if success is None:
            updated_success = existing_success
        else:
            updated_success = SUCCESS_STRING[success]

        node_color = SUCCESS_COLORS[updated_success]
        updated_graph, updated_color_preview = self._color_graph_nodes(graph, node_color)

        graph_json = json.dumps(updated_graph)
        color_preview_json = json.dumps(updated_color_preview)
        self.backend.update_experiment_log_query(
            updated_log, updated_success, color_preview_json, graph_json, session_id
        )

        return updated_graph

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
        raise ValueError(f"Parent session not found for session_id: {session_id}")

    def cache_file(self, file_id, file_name, io_stream):
        """Cache file attachment."""
        if not getattr(self, "cache_attachments", False):
            return
        if self.backend.check_attachment_exists_query(file_id):
            return
        from ao.common.utils import stream_hash, save_io_stream

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
        from ao.runner.context_manager import get_session_id
        from ao.common.utils import hash_input, set_seed
        from ao.runner.monkey_patching.patching_utils import capture_stack_trace

        # Capture stack trace early (before any internal calls pollute it)
        stack_trace = capture_stack_trace()

        input_pickle, _ = func_kwargs_to_json_str(input_dict, api_type)
        input_hash = hash_input(input_pickle)

        session_id = get_session_id()

        row = self.backend.get_llm_call_by_session_and_hash_query(session_id, input_hash)

        if row is None:
            logger.debug(
                f"Cache miss: session_id {str(session_id)[:4]}, input_hash {str(input_hash)[:4]}"
            )
            return CacheOutput(
                input_dict=input_dict,
                output=None,
                node_id=None,
                input_pickle=input_pickle,
                input_hash=input_hash,
                session_id=session_id,
                stack_trace=stack_trace,
            )

        node_id = row["node_id"]
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

        set_seed(node_id)
        return CacheOutput(
            input_dict=input_dict,
            output=output,
            node_id=node_id,
            input_pickle=input_pickle,
            input_hash=input_hash,
            session_id=session_id,
            stack_trace=stack_trace,
        )

    def cache_output(
        self, cache_result: CacheOutput, output_obj: Any, api_type: str, cache: bool = True
    ) -> None:
        """Cache the output of an LLM call."""
        from ao.common.utils import set_seed

        # Reset randomness to avoid generating exact same UUID when re-running
        random.seed()
        if cache_result.node_id:
            node_id = cache_result.node_id
        else:
            node_id = str(uuid.uuid4())
        response_ok = api_obj_to_response_ok(output_obj, api_type)

        if response_ok and cache:
            output_json_str = api_obj_to_json_str(output_obj, api_type)
            self.backend.insert_llm_call_with_output_query(
                cache_result.session_id,
                cache_result.input_pickle,
                cache_result.input_hash,
                node_id,
                api_type,
                output_json_str,
                cache_result.stack_trace,
            )
        else:
            logger.warning(f"Node {node_id} response not OK.")
        cache_result.node_id = node_id
        cache_result.output = output_obj
        set_seed(node_id)

    def get_finished_runs(self, project_id=None):
        return self.backend.get_finished_runs_query(project_id=project_id)

    def get_all_experiments_sorted(self, limit=None, offset=0, project_id=None):
        return self.backend.get_all_experiments_sorted_query(limit=limit, offset=offset, project_id=project_id)

    def get_experiments_by_ids(self, session_ids, project_id=None):
        return self.backend.get_experiments_by_ids_query(session_ids, project_id=project_id)

    def get_experiments_excluding_ids(self, session_ids, limit=None, offset=0, project_id=None):
        return self.backend.get_experiments_excluding_ids_query(session_ids, limit=limit, offset=offset, project_id=project_id)

    def get_experiment_count(self, project_id=None):
        return self.backend.get_experiment_count_query(project_id=project_id)

    def get_experiment_count_excluding_ids(self, session_ids, project_id=None):
        return self.backend.get_experiment_count_excluding_ids_query(session_ids, project_id=project_id)

    def get_experiment_detail(self, session_id):
        return self.backend.get_experiment_detail_query(session_id)

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

    def delete_user(self, user_id):
        self.backend.delete_user_query(user_id)

    def get_session_name(self, session_id):
        row = self.backend.get_session_name_query(session_id)
        if not row:
            return []
        return [row["name"]]

    def query_one_llm_call_input(self, session_id, node_id):
        return self.backend.get_llm_call_input_api_type_query(session_id, node_id)

    def query_one_llm_call_output(self, session_id, node_id):
        return self.backend.get_llm_call_output_api_type_query(session_id, node_id)

    def get_next_run_index(self, project_id=None):
        return self.backend.get_next_run_index_query(project_id=project_id)

    # Project operations
    def get_project(self, project_id):
        return self.backend.get_project_query(project_id)

    def upsert_project(self, project_id, name, description):
        self.backend.upsert_project_query(project_id, name, description)

    def update_project_last_run_at(self, project_id):
        self.backend.update_project_last_run_at_query(project_id)

    def get_all_projects(self):
        return self.backend.get_all_projects_query()

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

    def get_project_locations(self, user_id, project_id):
        return self.backend.get_project_locations_query(user_id, project_id)

    # Probe-related methods for ao-tool
    def get_experiment_metadata(self, session_id):
        return self.backend.get_experiment_metadata_query(session_id)

    def get_llm_calls_for_session(self, session_id):
        return self.backend.get_llm_calls_for_session_query(session_id)

    def get_llm_call_full(self, session_id, node_id):
        return self.backend.get_llm_call_full_query(session_id, node_id)

    def copy_llm_calls(self, old_session_id, new_session_id):
        self.backend.copy_llm_calls_query(old_session_id, new_session_id)

    # ============================================================
    # Lessons Applied operations (tracks which ao-playbook lessons were applied)
    # ============================================================

    def get_all_lessons_applied(self):
        """Get all lesson application records for merging with ao-playbook lesson data."""
        rows = self.backend.get_all_lessons_applied_query()
        return [
            {
                "lesson_id": row["lesson_id"],
                "session_id": row["session_id"],
                "node_id": row["node_id"],
                "run_name": row["run_name"] or "Unknown Run",
            }
            for row in rows
        ]

    def get_lessons_applied_for_lesson(self, lesson_id):
        rows = self.backend.get_lessons_applied_query(lesson_id)
        return [
            {
                "sessionId": row["session_id"],
                "nodeId": row["node_id"],
                "runName": row["run_name"] or "Unknown Run",
            }
            for row in rows
        ]

    def add_lesson_applied(self, lesson_id, session_id, node_id=None):
        self.backend.add_lesson_applied_query(lesson_id, session_id, node_id)

    def remove_lesson_applied(self, lesson_id, session_id, node_id=None):
        self.backend.remove_lesson_applied_query(lesson_id, session_id, node_id)

    def delete_lessons_applied_for_lesson(self, lesson_id):
        self.backend.delete_lessons_applied_for_lesson_query(lesson_id)


# Create singleton instance following the established pattern
DB = DatabaseManager()
