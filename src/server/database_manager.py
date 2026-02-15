"""
Database manager for handling dynamic switching between SQLite and PostgreSQL backends.

This module provides a unified interface for database operations while supporting
runtime switching between local SQLite and remote PostgreSQL databases.
"""

import time
import uuid
import json
import random
from dataclasses import dataclass
from typing import Optional, Any

from ao.common.logger import logger

# NOTE: postgres backend is currently disabled - uncomment when needed
# from ao.server.database_backends import postgres
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
    """
    Manages database backend selection and routes operations to appropriate backend.

    Supports switching between:
    - Local mode: SQLite database for local development
    - Remote mode: PostgreSQL database for shared/production use
    """

    def __init__(self):
        """Initialize with default SQLite backend."""
        # Default to SQLite, user can switch via UI dropdown
        self._backend_type = "sqlite"

        # Lazy-loaded backend module
        self._backend_module = None

        # Check if and where to cache attachments.
        from ao.common.constants import ATTACHMENT_CACHE

        self.cache_attachments = True
        self.attachment_cache_dir = ATTACHMENT_CACHE

        logger.info(f"DatabaseManager initialized with backend: {self.get_current_mode()}")

    @property
    def backend(self):
        """
        Lazy load and return the appropriate backend module.

        Returns:
            Backend module (sqlite or postgres) with database functions
        """
        if self._backend_module is None:
            if self._backend_type == "sqlite":
                from ao.server.database_backends import sqlite

                self._backend_module = sqlite
                logger.debug("Loaded SQLite backend module")
            elif self._backend_type == "postgres":
                from ao.server.database_backends import postgres

                self._backend_module = postgres
                logger.debug("Loaded PostgreSQL backend module")
            else:
                raise ValueError(f"Unknown backend type: {self._backend_type}")
        return self._backend_module

    def switch_mode(self, mode: str):
        """
        Switch between 'local' (SQLite) and 'remote' (PostgreSQL) database modes.

        Args:
            mode: Either 'local' for SQLite or 'remote' for PostgreSQL

        Raises:
            ValueError: If mode is not 'local' or 'remote'
        """
        if mode == "local":
            self._backend_type = "sqlite"
            logger.info("Switched to local SQLite database")
        elif mode == "remote":
            self._backend_type = "postgres"
            logger.info("Switched to remote PostgreSQL database")
        else:
            raise ValueError(f"Invalid mode: {mode}. Use 'local' or 'remote'")

        # Clear cached backend and connections to force reload with new backend
        self._backend_module = None
        self._clear_backend_connections()

    def _clear_backend_connections(self):
        """Clear cached connections in the current backend to force reconnection."""
        if self._backend_module:
            try:
                self._backend_module.clear_connections()
            except Exception as e:
                logger.warning(f"Error clearing backend connections: {e}")

    def get_current_mode(self) -> str:
        """
        Get the current database mode.

        Returns:
            'local' if using SQLite, 'remote' if using PostgreSQL
        """
        return "local" if self._backend_type == "sqlite" else "remote"

    # Low-level database operations (direct backend access)
    def query_one(self, query, params=None):
        """Execute query and return single row result."""
        return self.backend.query_one(query, params or ())

    def query_all(self, query, params=None):
        """Execute query and return all rows."""
        return self.backend.query_all(query, params or ())

    def execute(self, query, params=None):
        """Execute query without returning results."""
        return self.backend.execute(query, params or ())

    # NOTE: Auth disabled - user management methods commented out
    # def upsert_user(self, google_id, email, name, picture):
    #     """
    #     Upsert user in the database.
    #
    #     Args:
    #         google_id: Google OAuth ID
    #         email: User email
    #         name: User name
    #         picture: User profile picture URL
    #
    #     Returns:
    #         User record from the database
    #
    #     Raises:
    #         Exception: If current backend doesn't support user management (e.g., SQLite)
    #     """
    #     return postgres.upsert_user(google_id, email, name, picture)
    #
    # def get_user_by_id(self, user_id):
    #     """
    #     Get user by their ID from the database.
    #
    #     Args:
    #         user_id: The user's ID
    #
    #     Returns:
    #         The user record or None if not found
    #
    #     Raises:
    #         Exception: If current backend doesn't support user management (e.g., SQLite)
    #     """
    #     return self.backend.get_user_by_id_query(user_id)

    def set_input_overwrite(self, session_id, node_id, new_input):
        # Normalize JSON representation
        new_input = json.dumps(json.loads(new_input), sort_keys=True)
        row = self.backend.get_llm_call_input_api_type_query(session_id, node_id)
        original_input = json.dumps(json.loads(row["input"]), sort_keys=True)
        # Only clear output if input actually changed
        if original_input != new_input:
            self.backend.set_input_overwrite_query(new_input, session_id, node_id)

    def set_output_overwrite(self, session_id, node_id, new_output: str):
        # Overwrite output for node.
        row = self.backend.get_llm_call_output_api_type_query(session_id, node_id)

        if not row:
            logger.error(
                f"No llm_calls record found for session_id={session_id}, node_id={node_id}"
            )
            return

        try:
            # try to parse the edit of the user
            json_str_to_api_obj(new_output, row["api_type"])
            new_output = json.dumps(json.loads(new_output), sort_keys=True)
            self.backend.set_output_overwrite_query(new_output, session_id, node_id)
        except Exception as e:
            logger.error(f"Failed to parse output edit into API object: {e}")

    def erase(self, session_id):
        """Erase experiment data."""
        import json

        default_graph = json.dumps({"nodes": [], "edges": []})
        self.backend.delete_llm_calls_query(session_id)
        self.backend.update_experiment_graph_topology_query(default_graph, session_id)

    def add_experiment(
        self,
        session_id,
        name,
        timestamp,
        cwd,
        command,
        environment,
        parent_session_id=None,
        user_id=None,
        version_date=None,
    ):
        """Add experiment to database."""
        import json
        from ao.common.constants import DEFAULT_LOG, DEFAULT_NOTE, DEFAULT_SUCCESS

        # Initial values.
        default_graph = json.dumps({"nodes": [], "edges": []})
        parent_session_id = parent_session_id if parent_session_id else session_id
        env_json = json.dumps(environment)

        # Use database backend to execute backend-specific SQL
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
            user_id,
            version_date,
        )

    def update_graph_topology(self, session_id, graph_dict):
        """Update graph topology."""
        import json

        graph_json = json.dumps(graph_dict)
        self.backend.update_experiment_graph_topology_query(graph_json, session_id)

    def update_timestamp(self, session_id, timestamp):
        """Update the timestamp of an experiment (used for reruns)."""
        self.backend.update_experiment_timestamp_query(timestamp, session_id)

    def update_run_name(self, session_id, run_name):
        """Update the experiment name/title."""
        self.backend.update_experiment_name_query(run_name, session_id)

    def update_result(self, session_id, result):
        """Update the experiment result/success status."""
        self.backend.update_experiment_result_query(result, session_id)

    def update_notes(self, session_id, notes):
        """Update the experiment notes."""
        self.backend.update_experiment_notes_query(notes, session_id)

    def update_command(self, session_id, command):
        """Update the experiment restart command."""
        self.backend.update_experiment_command_query(command, session_id)

    def update_experiment_version_date(self, session_id, version_date):
        """Update the version_date for an existing experiment."""
        self.backend.update_experiment_version_date_query(version_date, session_id)

    def _color_graph_nodes(self, graph, color):
        """Update border_color for each node."""
        # Update border_color for each node
        for node in graph.get("nodes", []):
            node["border_color"] = color

        # Create color preview list with one color entry per node
        color_preview = [color for _ in graph.get("nodes", [])]

        return graph, color_preview

    def add_log(self, session_id, success, new_entry):
        """Write success and new_entry to DB under certain conditions."""
        import json
        from ao.common.constants import DEFAULT_LOG, SUCCESS_STRING, SUCCESS_COLORS

        row = self.backend.get_experiment_log_success_graph_query(session_id)

        existing_log = row["log"]
        existing_success = row["success"]
        graph = json.loads(row["graph_topology"])

        # Handle log entry logic
        if new_entry is None:
            # If new_entry is None, leave the existing entry
            updated_log = existing_log
        elif existing_log == DEFAULT_LOG:
            # If the log is empty, set it to the new entry
            updated_log = new_entry
        else:
            # If log has entries, append the new entry
            updated_log = existing_log + "\n" + new_entry

        # Handle success logic
        if success is None:
            updated_success = existing_success
        else:
            updated_success = SUCCESS_STRING[success]

        # Color nodes.
        node_color = SUCCESS_COLORS[updated_success]
        updated_graph, updated_color_preview = self._color_graph_nodes(graph, node_color)

        # Update experiments table with new `log`, `success`, `color_preview`, and `graph_topology`
        graph_json = json.dumps(updated_graph)
        color_preview_json = json.dumps(updated_color_preview)
        self.backend.update_experiment_log_query(
            updated_log, updated_success, color_preview_json, graph_json, session_id
        )

        return updated_graph

    # Cache Management Operations (from CacheManager)
    def get_subrun_id(self, parent_session_id, name):
        """Get subrun session ID by parent session and name."""
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

        # If we get here, all retries failed
        logger.error(f"Failed to find parent session for {session_id} after {max_retries} attempts")
        raise ValueError(f"Parent session not found for session_id: {session_id}")

    def cache_file(self, file_id, file_name, io_stream):
        """Cache file attachment."""
        if not getattr(self, "cache_attachments", False):
            return
        # Early exit if file_id already exists
        if self.backend.check_attachment_exists_query(file_id):
            return
        # Check if with same content already exists.
        from ao.common.utils import stream_hash, save_io_stream

        content_hash = stream_hash(io_stream)
        row = self.backend.get_attachment_by_content_hash_query(content_hash)
        # Get appropriate file_path.
        if row is not None:
            file_path = row["file_path"]
        else:
            file_path = save_io_stream(io_stream, file_name, self.attachment_cache_dir)
        # Insert the file_id mapping
        self.backend.insert_attachment_query(file_id, content_hash, file_path)

    def get_file_path(self, file_id):
        """Get file path for cached attachment."""
        if not getattr(self, "cache_attachments", False):
            return None
        row = self.backend.get_attachment_file_path_query(file_id)
        if row is not None:
            return row["file_path"]
        return None

    def attachment_ids_to_paths(self, attachment_ids):
        """Convert attachment IDs to file paths."""
        # file_path can be None if user doesn't want to cache?
        file_paths = [self.get_file_path(attachment_id) for attachment_id in attachment_ids]
        # assert all(f is not None for f in file_paths), "All file paths should be non-None"
        return [f for f in file_paths if f is not None]

    def get_in_out(self, input_dict: dict, api_type: str) -> CacheOutput:
        """Get input/output for LLM call, handling caching and overwrites."""
        from ao.runner.context_manager import get_session_id
        from ao.common.utils import hash_input, set_seed
        from ao.runner.monkey_patching.patching_utils import capture_stack_trace

        # Capture stack trace early (before any internal calls pollute it)
        stack_trace = capture_stack_trace()

        # Cache key is the serialized input (URL + body for HTTP APIs)
        input_pickle, _ = func_kwargs_to_json_str(input_dict, api_type)
        input_hash = hash_input(input_pickle)

        # Check if API call with same session_id & input has been made before.
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

        # Use data from previous LLM call.
        node_id = row["node_id"]
        output = None

        if row["input_overwrite"] is not None:
            logger.debug(
                f"Cache hit (input overwritten): session_id {str(session_id)[:4]}, input_hash {str(input_hash)[:4]}"
            )
            input_dict = json_str_to_original_inp_dict(row["input_overwrite"], input_dict, api_type)

        # Here, no matter if we made an edit to the input or not, the input dict should
        # be a valid input to the underlying function

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
        """
        Cache the output of an LLM call using information from a CacheOutput object.

        Args:
            cache_result: CacheOutput object containing cache information
            output_obj: The output object to cache
            api_type: The API type identifier
            cache: Whether to actually cache the result

        Returns:
            The node_id assigned to this LLM call
        """
        from ao.common.utils import set_seed

        # Insert new row with a new node_id. reset randomness to avoid
        # generating exact same UUID when re-running, but MCP generates randomness and we miss cache
        random.seed()
        if cache_result.node_id:
            node_id = cache_result.node_id
        else:
            node_id = str(uuid.uuid4())
        # Avoid caching bad http responses
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

    def get_finished_runs(self):
        """Get all finished runs."""
        return self.backend.get_finished_runs_query()

    def get_all_experiments_sorted(self):
        """Get all experiments sorted by timestamp (most recent first)."""
        # Auth disabled - return all experiments without user filtering
        return self.backend.get_all_experiments_sorted_query()

    def get_graph(self, session_id):
        """Get graph topology for session."""
        return self.backend.get_experiment_graph_topology_query(session_id)

    def get_color_preview(self, session_id):
        """Get color preview for session."""
        row = self.backend.get_experiment_color_preview_query(session_id)
        if row and row["color_preview"]:
            return json.loads(row["color_preview"])
        return []

    def get_parent_environment(self, parent_session_id):
        """Get parent environment info."""
        return self.backend.get_experiment_environment_query(parent_session_id)

    def delete_llm_calls_query(self, session_id):
        return self.backend.delete_llm_calls_query(session_id)

    def delete_all_llm_calls_query(self):
        """Delete all records from llm_calls table."""
        return self.backend.delete_all_llm_calls_query()

    def update_color_preview(self, session_id, colors):
        """Update color preview."""
        color_preview_json = json.dumps(colors)
        self.backend.update_experiment_color_preview_query(color_preview_json, session_id)

    def get_exec_command(self, session_id):
        """Get execution command info."""
        row = self.backend.get_experiment_exec_info_query(session_id)
        if row is None:
            return None, None, None
        return row["cwd"], row["command"], json.loads(row["environment"])

    def clear_db(self):
        """Delete all records from experiments and llm_calls tables."""
        self.backend.delete_all_experiments_query()
        self.backend.delete_all_llm_calls_query()

    def get_session_name(self, session_id):
        """Get session name."""
        # Get all subrun names for this parent session
        row = self.backend.get_session_name_query(session_id)
        if not row:
            return []  # Return empty list if no subruns found
        return [row["name"]]

    def query_one_llm_call_input(self, session_id, node_id):
        """Get one llm-call input by session id and node id"""
        return self.backend.get_llm_call_input_api_type_query(session_id, node_id)

    def query_one_llm_call_output(self, session_id, node_id):
        """Get one llm-call output by session id and node id"""
        return self.backend.get_llm_call_output_api_type_query(session_id, node_id)

    def get_next_run_index(self):
        """Get the next run index based on how many runs already exist."""
        return self.backend.get_next_run_index_query()

    # Probe-related methods for ao-tool
    def get_experiment_metadata(self, session_id):
        """Get experiment metadata for probe command."""
        return self.backend.get_experiment_metadata_query(session_id)

    def get_llm_calls_for_session(self, session_id):
        """Get all LLM calls for a session."""
        return self.backend.get_llm_calls_for_session_query(session_id)

    def get_llm_call_full(self, session_id, node_id):
        """Get full LLM call data including input, output, and overwrites."""
        return self.backend.get_llm_call_full_query(session_id, node_id)

    def copy_llm_calls(self, old_session_id, new_session_id):
        """Copy all LLM calls from one session to another."""
        self.backend.copy_llm_calls_query(old_session_id, new_session_id)

    # ============================================================
    # Lessons Applied operations (tracks which ao-playbook lessons were applied)
    # ============================================================

    def get_all_lessons_applied(self):
        """
        Get all lesson application records for merging with ao-playbook lesson data.

        Returns:
            List of dicts: [{"lesson_id": str, "session_id": str, "node_id": str, "run_name": str}, ...]
        """
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
        """Get all sessions/nodes where a specific lesson was applied."""
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
        """Record that a lesson was applied to a session/node."""
        self.backend.add_lesson_applied_query(lesson_id, session_id, node_id)

    def remove_lesson_applied(self, lesson_id, session_id, node_id=None):
        """Remove a lesson application record."""
        self.backend.remove_lesson_applied_query(lesson_id, session_id, node_id)

    def delete_lessons_applied_for_lesson(self, lesson_id):
        """Delete all application records for a lesson (when lesson is deleted from ao-playbook)."""
        self.backend.delete_lessons_applied_for_lesson_query(lesson_id)


# Create singleton instance following the established pattern
DB = DatabaseManager()
