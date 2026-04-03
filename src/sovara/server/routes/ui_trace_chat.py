"""Trace-chat persistence and proxy UI routes."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from sovara.server.app import get_state
from sovara.server.database import DB, BadRequestError, ResourceNotFoundError
from sovara.server.state import ServerState, logger

from .ui_common import request_error_response

router = APIRouter()

TRACE_CHAT_CANCELED_DETAIL = "Trace chat canceled"


def _extract_http_error_detail(resp) -> str:
    try:
        data = resp.json()
    except ValueError:
        text = resp.text.strip()
        return text or "Chat error"

    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
        error = data.get("error")
        if isinstance(error, str) and error.strip():
            return error

    return "Chat error"


class PersistedTraceChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatMessageRequest(BaseModel):
    message: str
    history: list[PersistedTraceChatMessage] = Field(default_factory=list)


class PersistedTraceChatHistoryRequest(BaseModel):
    history: list[PersistedTraceChatMessage]


@router.get("/trace-chat/{run_id}")
def get_trace_chat_history(run_id: str):
    try:
        history = DB.get_trace_chat_history(run_id)
    except (BadRequestError, ResourceNotFoundError) as exc:
        return request_error_response(exc)
    return {"history": history}


@router.post("/trace-chat/{run_id}")
def update_trace_chat_history(run_id: str, req: PersistedTraceChatHistoryRequest):
    try:
        DB.update_trace_chat_history(
            run_id,
            [message.model_dump() for message in req.history],
        )
        history = DB.get_trace_chat_history(run_id)
    except (BadRequestError, ResourceNotFoundError) as exc:
        return request_error_response(exc)
    return {"history": history}


@router.post("/trace-chat/{run_id}/clear")
def clear_trace_chat_history(run_id: str):
    try:
        DB.clear_trace_chat_history(run_id)
    except (BadRequestError, ResourceNotFoundError) as exc:
        return request_error_response(exc)
    return {"history": []}


@router.post("/prefetch/{run_id}", status_code=202)
async def prefetch_trace(
    run_id: str,
    state: ServerState = Depends(get_state),
):
    run_map, _running_ids = state.get_run_snapshot()
    run = run_map.get(run_id)
    if run and run.status == "running":
        return {"status": "skipped", "reason": "run_still_active"}

    import httpx

    from sovara.common.constants import HOST, INFERENCE_PORT

    async with httpx.AsyncClient() as client:
        await client.post(
            f"http://{HOST}:{INFERENCE_PORT}/prefetch/{run_id}",
            timeout=5.0,
        )
    return {"status": "prefetching"}


@router.post("/chat/{run_id}")
async def chat(run_id: str, req: ChatMessageRequest, state: ServerState = Depends(get_state)):
    import httpx

    from sovara.common.constants import HOST, INFERENCE_PORT

    generation = state.begin_trace_chat_request(run_id)
    persisted_history = [message.model_dump() for message in req.history] + [
        {"role": "user", "content": req.message}
    ]

    def _is_cancelled_or_stale() -> bool:
        return (
            state.is_trace_chat_request_cancelled(run_id, generation)
            or not state.is_trace_chat_request_current(run_id, generation)
        )

    try:
        DB.update_trace_chat_history(run_id, persisted_history)
    except (BadRequestError, ResourceNotFoundError) as exc:
        state.finish_trace_chat_request(run_id, generation)
        return request_error_response(exc)

    timeout_seconds = 120.0
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://{HOST}:{INFERENCE_PORT}/chat/{run_id}",
                json=req.model_dump(),
                timeout=timeout_seconds,
            )
    except httpx.TimeoutException:
        if _is_cancelled_or_stale():
            state.finish_trace_chat_request(run_id, generation)
            raise HTTPException(409, TRACE_CHAT_CANCELED_DETAIL)
        logger.error("Trace chat proxy timed out after %.1fs for run %s", timeout_seconds, run_id)
        state.finish_trace_chat_request(run_id, generation)
        raise HTTPException(504, f"Trace chat timed out after {int(timeout_seconds)} seconds")
    except httpx.HTTPError as exc:
        if _is_cancelled_or_stale():
            state.finish_trace_chat_request(run_id, generation)
            raise HTTPException(409, TRACE_CHAT_CANCELED_DETAIL)
        logger.error("Trace chat proxy failed for run %s: %s", run_id, exc)
        state.finish_trace_chat_request(run_id, generation)
        raise HTTPException(502, "Could not reach inference server")
    if resp.status_code != 200:
        detail = _extract_http_error_detail(resp)
        was_cancelled_or_stale = _is_cancelled_or_stale()
        state.finish_trace_chat_request(run_id, generation)
        if was_cancelled_or_stale or detail == TRACE_CHAT_CANCELED_DETAIL:
            raise HTTPException(409, TRACE_CHAT_CANCELED_DETAIL)
        raise HTTPException(resp.status_code, detail)
    try:
        data = resp.json()
    except ValueError:
        logger.error("Inference server returned invalid JSON for run %s", run_id)
        state.finish_trace_chat_request(run_id, generation)
        raise HTTPException(502, "Invalid response from inference server")

    if _is_cancelled_or_stale():
        state.finish_trace_chat_request(run_id, generation)
        raise HTTPException(409, TRACE_CHAT_CANCELED_DETAIL)

    answer = data.get("answer")
    if isinstance(answer, str):
        try:
            DB.update_trace_chat_history(
                run_id,
                persisted_history + [{"role": "assistant", "content": answer}],
            )
        except (BadRequestError, ResourceNotFoundError) as exc:
            state.finish_trace_chat_request(run_id, generation)
            return request_error_response(exc)
    try:
        history = DB.get_trace_chat_history(run_id)
    except (BadRequestError, ResourceNotFoundError) as exc:
        state.finish_trace_chat_request(run_id, generation)
        return request_error_response(exc)

    state.finish_trace_chat_request(run_id, generation)
    return {**data, "history": history}


@router.post("/chat/{run_id}/abort", status_code=202)
async def abort_trace_chat(run_id: str, state: ServerState = Depends(get_state)):
    import httpx

    from sovara.common.constants import HOST, INFERENCE_PORT

    generation = state.cancel_trace_chat_request(run_id)
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"http://{HOST}:{INFERENCE_PORT}/chat/{run_id}/abort",
                timeout=5.0,
            )
    except Exception as exc:
        logger.warning("Trace chat abort proxy failed for run %s: %s", run_id, exc)
    return {"status": "cancelling" if generation is not None else "idle"}
