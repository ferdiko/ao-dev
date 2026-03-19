"""SSE and WebSocket endpoints."""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from starlette.responses import StreamingResponse

from ao.server.state import ServerState, logger
from ao.common.constants import AO_CONFIG, PLAYBOOK_SERVER_URL, PLAYBOOK_API_KEY
from ao.server.routes import ui as ui_routes

router = APIRouter()


# ============================================================
# Runner SSE -- server pushes restart/shutdown to runners
# ============================================================

@router.get("/runner/events/{session_id}")
async def runner_events(session_id: str, request: Request):
    """SSE stream for a runner. Server pushes restart/shutdown events."""
    state: ServerState = request.app.state.server_state

    # Queue must exist (created by POST /runner/register)
    q = state.runner_event_queues.get(session_id)
    if not q:
        from starlette.responses import JSONResponse
        return JSONResponse({"error": "Session not registered"}, status_code=404)

    # Mark SSE as connected so the orphan sweep knows this runner is alive
    session = state.sessions.get(session_id)
    if session:
        session.sse_connected = True

    async def event_generator():
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            # Clean up queue and mark session finished on disconnect
            state.runner_event_queues.pop(session_id, None)
            session = state.sessions.get(session_id)
            if session and session.status == "running":
                session.status = "finished"
                state.notify_experiment_list_changed()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# UI WebSocket -- push graph/experiment updates
# ============================================================

@router.websocket("/ws")
async def ui_websocket(websocket: WebSocket):
    state: ServerState = websocket.app.state.server_state
    await websocket.accept()
    state.ui_websockets.add(websocket)

    # Send initial config
    await websocket.send_text(json.dumps({
        "type": "session_id",
        "session_id": None,
        "config_path": AO_CONFIG,
        "playbook_url": PLAYBOOK_SERVER_URL,
        "playbook_api_key": PLAYBOOK_API_KEY,
    }))

    # Load finished runs to ensure experiment list is current
    state.load_finished_runs()

    try:
        while True:
            data = await websocket.receive_text()
            state.touch_activity()
            try:
                msg = json.loads(data)
                await _handle_ws_message(websocket, state, msg)
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}")

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"UI WebSocket error: {e}")
    finally:
        state.ui_websockets.discard(websocket)


async def _handle_ws_message(ws: WebSocket, state: ServerState, msg: dict) -> None:
    """Route a WebSocket message to the corresponding REST endpoint."""
    msg_type = msg.get("type")
    session_id = msg.get("session_id")

    # Read-only: call REST endpoint, send result to this websocket
    if msg_type == "get_all_experiments":
        result = ui_routes.get_experiments(state)
        await ws.send_text(json.dumps(result))

    elif msg_type == "get_more_experiments":
        result = ui_routes.get_more_experiments(msg.get("offset", 0), state)
        await ws.send_text(json.dumps(result))

    elif msg_type == "get_graph":
        if session_id:
            result = ui_routes.get_graph(session_id, state)
            await ws.send_text(json.dumps(result))

    elif msg_type == "get_experiment_detail":
        if session_id:
            result = ui_routes.get_experiment_detail(session_id, state)
            await ws.send_text(json.dumps(result))

    elif msg_type == "get_lessons_applied":
        if not session_id:
            logger.error("get_lessons_applied requires session_id")
            return
        result = ui_routes.get_lessons_applied(session_id, state)
        await ws.send_text(json.dumps(result))

    elif msg_type == "get_sessions_for_lesson":
        lesson_id = msg.get("lesson_id")
        if not lesson_id:
            logger.error("get_sessions_for_lesson requires lesson_id")
            return
        result = ui_routes.get_sessions_for_lesson(lesson_id, state)
        await ws.send_text(json.dumps(result))

    # Mutations: call REST endpoint (broadcasting handled internally via schedule_*)
    elif msg_type == "edit_input":
        ui_routes.edit_input(ui_routes.EditInputRequest(
            session_id=msg["session_id"], node_id=msg["node_id"], value=msg["value"],
        ), state)

    elif msg_type == "edit_output":
        ui_routes.edit_output(ui_routes.EditOutputRequest(
            session_id=msg["session_id"], node_id=msg["node_id"], value=msg["value"],
        ), state)

    elif msg_type == "update_node":
        ui_routes.update_node(ui_routes.UpdateNodeRequest(
            session_id=msg["session_id"], node_id=msg["node_id"],
            field=msg["field"], value=msg["value"],
        ), state)

    elif msg_type == "update_run_name":
        ui_routes.update_run_name(ui_routes.UpdateRunNameRequest(
            session_id=msg["session_id"], run_name=msg["run_name"],
        ), state)

    elif msg_type == "update_result":
        ui_routes.update_result(ui_routes.UpdateResultRequest(
            session_id=msg["session_id"], result=msg["result"],
        ), state)

    elif msg_type == "update_notes":
        ui_routes.update_notes(ui_routes.UpdateNotesRequest(
            session_id=msg["session_id"], notes=msg["notes"],
        ), state)

    elif msg_type == "restart":
        if session_id:
            ui_routes.restart(ui_routes.RestartRequest(session_id=session_id), state)

    elif msg_type == "erase":
        if session_id:
            ui_routes.erase(ui_routes.EraseRequest(session_id=session_id), state)

    elif msg_type == "shutdown":
        ui_routes.shutdown(state)

    elif msg_type == "clear":
        ui_routes.clear(state)

    else:
        logger.debug(f"Unhandled WebSocket message type: {msg_type}")
