"""
Lesson injection for LLM contexts.

Queries the ao-playbook server for lessons and returns them formatted
for injection into prompts. Automatically tracks which lessons were
applied to which runs.
"""

import json
import os
import urllib.request
import urllib.error
from typing import Optional, List

from sovara.common.constants import PLAYBOOK_SERVER_URL
from sovara.common.logger import logger


def _playbook_request(endpoint: str, payload: dict) -> dict:
    """POST to ao-playbook and return parsed JSON response."""
    url = f"{PLAYBOOK_SERVER_URL}/api/v1{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("SOVARA_API_KEY")
    if api_key:
        headers["X-API-Key"] = api_key

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_all_lessons(path: Optional[str] = None) -> List[dict]:
    """Fetch all lessons from ao-playbook (no LLM filtering)."""
    payload = {}
    if path is not None:
        payload["path"] = path
    result = _playbook_request("/query/lessons", payload)
    return result.get("lessons", [])


def _retrieve_lessons(path: Optional[str], context: str) -> List[dict]:
    """Retrieve relevant lessons via LLM-based filtering on ao-playbook."""
    payload = {"context": context}
    if path is not None:
        payload["base_path"] = path
    result = _playbook_request("/query/lessons/retrieve", payload)
    return result.get("lessons", [])


def _format_lessons(lessons: List[dict]) -> str:
    """Format lessons into an injectable context block."""
    if not lessons:
        return ""
    blocks = [f"## {l['name']}\n{l['content']}" for l in lessons]
    return "<lessons>\n" + "\n\n".join(blocks) + "\n</lessons>"


def _track_lessons(lesson_ids: List[str]) -> None:
    """Track which lessons were applied to the current run."""
    try:
        from sovara.runner.context_manager import get_run_id
        run_id = get_run_id()
        if run_id:
            from sovara.server.database_manager import DB
            for lesson_id in lesson_ids:
                DB.add_lesson_applied(lesson_id, run_id)
            logger.debug(f"Tracked {len(lesson_ids)} lessons applied to run {run_id[:8]}")
    except Exception as e:
        logger.debug(f"Could not track lesson application: {e}")


def inject_lesson(
    path: Optional[str] = None,
    context: Optional[str] = None,
    method: str = "retrieve",
) -> str:
    """
    Retrieve lessons from the playbook server and return them as injected context.

    Args:
        path: Folder path to retrieve lessons from (e.g. 'beaver/retriever/').
        context: Context string for LLM-based retrieval (required when method="retrieve").
        method: "retrieve" (LLM-filtered), "all" (all lessons in path), or "none".

    Returns:
        Formatted lessons string, or empty string if unavailable.
    """
    if method == "none":
        return ""

    try:
        if method == "retrieve":
            if context is None:
                raise ValueError("context is required when method='retrieve'")
            lessons = _retrieve_lessons(path, context)
        elif method == "all":
            lessons = _fetch_all_lessons(path)
        else:
            raise ValueError(f"Unknown method: {method}")
    except (urllib.error.URLError, ConnectionError) as e:
        logger.warning(f"Playbook server unavailable: {e}")
        return ""
    except ValueError:
        raise
    except Exception as e:
        logger.warning(f"Failed to fetch lessons: {e}")
        return ""

    # Track which lessons were applied
    lesson_ids = [l.get("id") for l in lessons if l.get("id")]
    if lesson_ids:
        _track_lessons(lesson_ids)

    return _format_lessons(lessons)
