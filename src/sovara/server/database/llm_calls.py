import json
import random
import time
import uuid
from typing import Any

from sovara.common.logger import logger
from sovara.runner.monkey_patching.api_parser import (
    api_obj_to_json_str,
    api_obj_to_response_ok,
    func_kwargs_to_json_str,
    json_str_to_api_obj,
    json_str_to_original_inp_dict,
    merge_filtered_into_raw,
)

from ._shared import BadRequestError, CacheOutput, ResourceNotFoundError


class LlmCallsMixin:
    def _next_occurrence(self, run_id: str, input_hash: str) -> int:
        """Return and increment the lookup count for (run_id, input_hash)."""
        with self._occurrence_lock:
            key = (run_id, input_hash)
            occurrence = self._occurrence_counters[key]
            self._occurrence_counters[key] += 1
            return occurrence

    def next_cache_occurrence(self, run_id: str, input_hash: str) -> int:
        return self._next_occurrence(run_id, input_hash)

    def reset_occurrence_counters(self) -> None:
        with self._occurrence_lock:
            self._occurrence_counters.clear()

    def set_input_overwrite(self, run_id, node_uuid, new_input):
        """UI sends to_show data; merge into original raw to build full format for the runner."""
        try:
            new_to_show = json.loads(new_input)
        except json.JSONDecodeError as exc:
            raise BadRequestError(
                f"Invalid input JSON for run_id={run_id}, node_uuid={node_uuid}: {exc.msg}."
            ) from exc

        row = self.backend.get_llm_call_input_api_type_query(run_id, node_uuid)
        if not row:
            raise ResourceNotFoundError(
                f"Input node not found for run_id={run_id}, node_uuid={node_uuid}."
            )

        try:
            original = json.loads(row["input"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise BadRequestError(
                f"Stored input payload is invalid for run_id={run_id}, node_uuid={node_uuid}."
            ) from exc

        if not isinstance(original, dict) or "raw" not in original or "to_show" not in original:
            raise BadRequestError(
                f"Stored input payload is incomplete for run_id={run_id}, node_uuid={node_uuid}."
            )

        if json.dumps(new_to_show, sort_keys=True) == json.dumps(original["to_show"], sort_keys=True):
            return None

        merged_raw = merge_filtered_into_raw(original["raw"], new_to_show)
        overwrite = json.dumps({"raw": merged_raw, "to_show": new_to_show}, sort_keys=True)
        self.backend.set_input_overwrite_query(overwrite, run_id, node_uuid)
        return overwrite

    def set_output_overwrite(self, run_id, node_uuid, new_output: str):
        """UI sends to_show data; merge into original raw to build full format for the runner."""
        try:
            new_to_show = json.loads(new_output)
        except json.JSONDecodeError as exc:
            raise BadRequestError(
                f"Invalid output JSON for run_id={run_id}, node_uuid={node_uuid}: {exc.msg}."
            ) from exc

        row = self.backend.get_llm_call_output_api_type_query(run_id, node_uuid)
        if not row:
            raise ResourceNotFoundError(
                f"Output node not found for run_id={run_id}, node_uuid={node_uuid}."
            )
        if row["output"] is None:
            raise BadRequestError(
                f"No stored output is available for run_id={run_id}, node_uuid={node_uuid}."
            )

        try:
            original = json.loads(row["output"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise BadRequestError(
                f"Stored output payload is invalid for run_id={run_id}, node_uuid={node_uuid}."
            ) from exc

        if not isinstance(original, dict) or "raw" not in original or "to_show" not in original:
            raise BadRequestError(
                f"Stored output payload is incomplete for run_id={run_id}, node_uuid={node_uuid}."
            )

        try:
            merged_raw = merge_filtered_into_raw(original["raw"], new_to_show)
            overwrite = json.dumps({"raw": merged_raw, "to_show": new_to_show}, sort_keys=True)

            json_str_to_api_obj(overwrite, row["api_type"])
            self.backend.set_output_overwrite_query(overwrite, run_id, node_uuid)
            return overwrite
        except Exception as e:
            raise BadRequestError(
                f"Invalid output edit for run_id={run_id}, node_uuid={node_uuid}: {e}"
            ) from e

    def get_subrun_id(self, parent_run_id, name):
        result = self.backend.get_subrun_by_parent_and_name_query(parent_run_id, name)
        if result is None:
            return None
        return result["run_id"]

    def get_parent_run_id(self, run_id):
        """
        Get parent run ID with retry logic to handle race conditions.

        Since runs can be inserted and immediately restarted, there can be a race
        condition where the restart handler tries to read parent_run_id before the
        insert transaction is committed. This method retries a few times with short delays.
        """
        max_retries = 3
        retry_delay = 0.05

        for attempt in range(max_retries):
            result = self.backend.get_parent_run_id_query(run_id)
            if result is not None:
                return result["parent_run_id"]

            if attempt < max_retries - 1:
                logger.debug(
                    f"Parent run not found for {run_id}, retrying in {retry_delay}s "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(retry_delay)

        logger.error(f"Failed to find parent run for {run_id} after {max_retries} attempts")
        raise ResourceNotFoundError(f"Run not found: {run_id}")

    def cache_file(self, file_id, file_name, io_stream):
        """Cache file attachment."""
        if not getattr(self, "cache_attachments", False):
            return
        if self.backend.check_attachment_exists_query(file_id):
            return
        from sovara.common.utils import save_io_stream, stream_hash

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
        """Get input/output for an LLM call, handling caching and overwrites."""
        from sovara.common.utils import hash_input, set_seed
        from sovara.runner.context_manager import get_run_id
        from sovara.runner.monkey_patching.patching_utils import capture_stack_trace

        stack_trace = capture_stack_trace()
        input_pickle, _ = func_kwargs_to_json_str(input_dict, api_type)
        input_hash = hash_input(input_pickle)
        run_id = get_run_id()

        occurrence = self._next_occurrence(run_id, input_hash)
        row = self.backend.get_llm_call_by_run_and_hash_query(run_id, input_hash, offset=occurrence)

        if row is None:
            logger.debug(f"Cache miss: run_id {str(run_id)[:4]}, input_hash {str(input_hash)[:4]}")
            return CacheOutput(
                input_dict=input_dict,
                output=None,
                node_uuid=None,
                input_pickle=input_pickle,
                input_hash=input_hash,
                run_id=run_id,
                stack_trace=stack_trace,
            )

        node_uuid = row["node_uuid"]
        output = None

        if row["input_overwrite"] is not None:
            logger.debug(
                f"Cache hit (input overwritten): run_id {str(run_id)[:4]}, "
                f"input_hash {str(input_hash)[:4]}"
            )
            input_dict = json_str_to_original_inp_dict(row["input_overwrite"], input_dict, api_type)

        if row["output"] is not None:
            output = json_str_to_api_obj(row["output"], api_type)
            logger.debug(
                f"Cache hit (output set): run_id {str(run_id)[:4]}, input_hash {str(input_hash)[:4]}"
            )

        set_seed(node_uuid)
        return CacheOutput(
            input_dict=input_dict,
            output=output,
            node_uuid=node_uuid,
            input_pickle=input_pickle,
            input_hash=input_hash,
            run_id=run_id,
            stack_trace=stack_trace,
        )

    def cache_output(
        self, cache_result: CacheOutput, output_obj: Any, api_type: str, cache: bool = True
    ) -> None:
        """Cache the output of an LLM call."""
        from sovara.common.utils import set_seed

        random.seed()
        if cache_result.node_uuid:
            node_uuid = cache_result.node_uuid
        else:
            node_uuid = str(uuid.uuid4())
        response_ok = api_obj_to_response_ok(output_obj, api_type)

        if response_ok and cache:
            output_json_str = api_obj_to_json_str(output_obj, api_type)
            self.backend.insert_llm_call_with_output_query(
                cache_result.run_id,
                cache_result.input_pickle,
                cache_result.input_hash,
                node_uuid,
                api_type,
                output_json_str,
                cache_result.stack_trace,
            )
            self.checkpoint_active_runtime(cache_result.run_id)
        else:
            logger.warning(f"Node {node_uuid} response not OK.")
        cache_result.node_uuid = node_uuid
        cache_result.output = output_obj
        set_seed(node_uuid)

    def insert_llm_call_with_output(
        self, run_id, input_pickle, input_hash, node_uuid, api_type, output_pickle, stack_trace=None
    ):
        self.backend.insert_llm_call_with_output_query(
            run_id,
            input_pickle,
            input_hash,
            node_uuid,
            api_type,
            output_pickle,
            stack_trace,
        )

    def delete_llm_calls(self, run_id):
        return self.backend.delete_llm_calls_query(run_id)

    def delete_all_llm_calls(self):
        return self.backend.delete_all_llm_calls_query()

    def delete_llm_calls_query(self, run_id):
        return self.delete_llm_calls(run_id)

    def delete_all_llm_calls_query(self):
        return self.delete_all_llm_calls()

    def find_node_uuids_by_prefix(self, run_id, node_uuid_prefix):
        rows = self.backend.find_node_uuids_by_prefix_query(run_id, node_uuid_prefix)
        return [row["node_uuid"] for row in rows]

    def query_one_llm_call_input(self, run_id, node_uuid):
        return self.backend.get_llm_call_input_api_type_query(run_id, node_uuid)

    def query_one_llm_call_output(self, run_id, node_uuid):
        return self.backend.get_llm_call_output_api_type_query(run_id, node_uuid)

    def get_llm_calls_for_run(self, run_id):
        return self.backend.get_llm_calls_for_run_query(run_id)

    def get_llm_call_full(self, run_id, node_uuid):
        return self.backend.get_llm_call_full_query(run_id, node_uuid)

    def copy_llm_calls(self, old_run_id, new_run_id):
        self.backend.copy_llm_calls_query(old_run_id, new_run_id)
