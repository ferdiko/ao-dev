"""Handlers for lesson-related messages (proxied to ao-playbook API)."""

import json
import socket
import urllib.request
import urllib.error

from ao.common.constants import PLAYBOOK_SERVER_URL, PLAYBOOK_API_KEY
from ao.server.database_manager import DB
from ao.server.handlers.handler_utils import send_json, logger


def _playbook_request(method: str, endpoint: str, data: dict = None) -> dict:
    """Make HTTP request to ao-playbook server."""
    url = f"{PLAYBOOK_SERVER_URL}/api/v1{endpoint}"
    headers = {"Content-Type": "application/json"}
    if PLAYBOOK_API_KEY:
        headers["X-API-Key"] = PLAYBOOK_API_KEY

    logger.info(f"[Playbook] {method} {url} (API key: {'set' if PLAYBOOK_API_KEY else 'NOT SET'})")

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            if isinstance(result, dict):
                logger.info(f"[Playbook] Response status: {result.get('status', 'ok')}")
            else:
                logger.info(f"[Playbook] Response: list with {len(result)} items")
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"Playbook API error {e.code}: {error_body}")
        return {"error": f"API error: {e.code}", "detail": error_body}
    except urllib.error.URLError as e:
        logger.warning(f"Playbook server unavailable: {e.reason}")
        return {"error": "Playbook server unavailable"}
    except Exception as e:
        logger.error(f"Playbook request failed: {e}")
        return {"error": str(e)}


def _merge_lessons_with_applied(lessons: list) -> list:
    """Merge ao-playbook lessons with local applied data."""
    applied_records = DB.get_all_lessons_applied()
    applied_by_lesson = {}
    for record in applied_records:
        lid = record["lesson_id"]
        if lid not in applied_by_lesson:
            applied_by_lesson[lid] = []
        applied_by_lesson[lid].append(
            {
                "sessionId": record["session_id"],
                "nodeId": record["node_id"],
                "runName": record["run_name"],
            }
        )

    for lesson in lessons:
        lesson_id = lesson.get("id")
        if lesson_id and lesson_id in applied_by_lesson:
            lesson["appliedTo"] = applied_by_lesson[lesson_id]

    return lessons


def _broadcast_lessons_to_uis(server) -> None:
    """Broadcast updated lessons list to all UI connections."""
    result = _playbook_request("GET", "/lessons")
    lessons = result if isinstance(result, list) else result.get("lessons", [])
    if "error" not in result:
        merged = _merge_lessons_with_applied(lessons)
        server.broadcast_to_all_uis({"type": "lessons_list", "lessons": merged})


def handle_get_lessons(server, conn: socket.socket) -> None:
    """Fetch lessons from ao-playbook and merge with local applied data."""
    result = _playbook_request("GET", "/lessons")

    if "error" in result:
        send_json(conn, {"type": "lessons_list", "lessons": [], "error": result["error"]})
        return

    lessons = result if isinstance(result, list) else result.get("lessons", [])
    merged = _merge_lessons_with_applied(lessons)
    send_json(conn, {"type": "lessons_list", "lessons": merged})


def handle_add_lesson(server, msg: dict, conn: socket.socket) -> None:
    """Create lesson via ao-playbook API with validation feedback."""
    data = {
        "name": msg.get("name", ""),
        "summary": msg.get("summary", ""),
        "content": msg.get("content", ""),
        "path": msg.get("path", ""),
    }

    if not data["name"] or not data["content"]:
        logger.error("add_lesson: Missing required fields (name, content)")
        send_json(
            conn, {"type": "lesson_error", "error": "Missing required fields (name, content)"}
        )
        return

    force = msg.get("force", False)
    endpoint = "/lessons" + ("?force=true" if force else "")

    result = _playbook_request("POST", endpoint, data)

    if result.get("status") == "rejected":
        reason = result.get("reason", "Validation failed")
        hint = result.get("hint")
        if hint:
            reason = f"{reason}\n\nHint: {hint}"
        send_json(
            conn,
            {
                "type": "lesson_rejected",
                "reason": reason,
                "severity": "error",
                "conflicting_lesson_ids": result.get("conflicting_lesson_ids", []),
            },
        )
    elif "error" in result:
        send_json(conn, {"type": "lesson_error", "error": result.get("error", "Unknown error")})
    elif result.get("status") == "created":
        validation = result.get("validation")
        send_json(
            conn,
            {
                "type": "lesson_created",
                "lesson": result,
                "validation": validation,
            },
        )
        _broadcast_lessons_to_uis(server)
    else:
        logger.warning(f"Unexpected add_lesson response: {result}")
        send_json(conn, {"type": "lesson_error", "error": "Unexpected server response"})


def handle_update_lesson(server, msg: dict, conn: socket.socket) -> None:
    """Update lesson via ao-playbook API with validation feedback."""
    lesson_id = msg.get("lesson_id")
    if not lesson_id:
        logger.error("update_lesson: Missing lesson_id")
        send_json(conn, {"type": "lesson_error", "error": "Missing lesson_id"})
        return

    data = {}
    for field in ["name", "summary", "content", "path"]:
        if field in msg:
            data[field] = msg[field]

    if not data:
        logger.error("update_lesson: No fields to update")
        send_json(conn, {"type": "lesson_error", "error": "No fields to update"})
        return

    force = msg.get("force", False)
    endpoint = f"/lessons/{lesson_id}" + ("?force=true" if force else "")

    result = _playbook_request("PUT", endpoint, data)

    if result.get("status") == "rejected":
        reason = result.get("reason", "Validation failed")
        hint = result.get("hint")
        if hint:
            reason = f"{reason}\n\nHint: {hint}"
        send_json(
            conn,
            {
                "type": "lesson_rejected",
                "reason": reason,
                "severity": "error",
                "conflicting_lesson_ids": result.get("conflicting_lesson_ids", []),
            },
        )
    elif "error" in result:
        send_json(conn, {"type": "lesson_error", "error": result.get("error", "Unknown error")})
    elif result.get("status") == "updated":
        validation = result.get("validation")
        send_json(
            conn,
            {
                "type": "lesson_updated",
                "lesson": result,
                "validation": validation,
            },
        )
        _broadcast_lessons_to_uis(server)
    else:
        logger.warning(f"Unexpected update_lesson response: {result}")
        send_json(conn, {"type": "lesson_error", "error": "Unexpected server response"})


def handle_delete_lesson(server, msg: dict, conn: socket.socket) -> None:
    """Delete lesson via ao-playbook API and clean up local applied records."""
    lesson_id = msg.get("lesson_id")
    if not lesson_id:
        logger.error("delete_lesson: Missing lesson_id")
        send_json(conn, {"type": "lesson_error", "error": "Missing lesson_id"})
        return

    result = _playbook_request("DELETE", f"/lessons/{lesson_id}")
    if "error" in result:
        send_json(conn, {"type": "lesson_error", "error": result.get("error", "Unknown error")})
    else:
        DB.delete_lessons_applied_for_lesson(lesson_id)
        _broadcast_lessons_to_uis(server)


def handle_get_lesson(server, msg: dict, conn: socket.socket) -> None:
    """Fetch a single lesson's full content via ao-playbook API."""
    lesson_id = msg.get("lesson_id")
    if not lesson_id:
        logger.error("get_lesson: Missing lesson_id")
        send_json(conn, {"type": "lesson_error", "error": "Missing lesson_id"})
        return

    result = _playbook_request("GET", f"/lessons/{lesson_id}")
    if "error" in result:
        send_json(conn, {"type": "lesson_error", "error": result.get("error", "Unknown error")})
    else:
        lesson = result.get("lesson", result)
        send_json(conn, {"type": "lesson_content", "lesson": lesson})
