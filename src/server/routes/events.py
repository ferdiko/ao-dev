"""SSE and WebSocket endpoints."""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from starlette.responses import StreamingResponse

from ao.server.state import ServerState, logger
from ao.common.constants import AO_CONFIG, PLAYBOOK_SERVER_URL, PLAYBOOK_API_KEY

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
    """Push-only WebSocket for server→UI broadcasts (graph updates, experiment list, etc.)."""
    state: ServerState = websocket.app.state.server_state
    # Accept UIs request to start a WebSocket connection
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

    # Load finished runs and send initial experiment list
    state.load_finished_runs()
    state.notify_experiment_list_changed()

    try:
        # Keep connection alive — just consume incoming messages (pings/keepalives)
        while True:
            await websocket.receive_text()
            state.touch_activity()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"UI WebSocket error: {e}")
    finally:
        state.ui_websockets.discard(websocket)
