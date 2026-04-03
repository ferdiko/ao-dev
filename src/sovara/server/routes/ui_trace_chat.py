"""Trace-chat persistence and proxy UI routes."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from sovara.server.app import get_state
from sovara.server.database import BadRequestError, ResourceNotFoundError
from sovara.server.services import trace_chat_service
from sovara.server.state import ServerState

from .ui_common import request_error_response

router = APIRouter()


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
        history = trace_chat_service.get_trace_chat_history(run_id)
    except (BadRequestError, ResourceNotFoundError) as exc:
        return request_error_response(exc)
    return {"history": history}


@router.post("/trace-chat/{run_id}")
def update_trace_chat_history(run_id: str, req: PersistedTraceChatHistoryRequest):
    try:
        history = trace_chat_service.update_trace_chat_history(
            run_id,
            [message.model_dump() for message in req.history],
        )
    except (BadRequestError, ResourceNotFoundError) as exc:
        return request_error_response(exc)
    return {"history": history}


@router.post("/trace-chat/{run_id}/clear")
def clear_trace_chat_history(run_id: str):
    try:
        trace_chat_service.clear_trace_chat_history(run_id)
    except (BadRequestError, ResourceNotFoundError) as exc:
        return request_error_response(exc)
    return {"history": []}


@router.post("/prefetch/{run_id}", status_code=202)
async def prefetch_trace(
    run_id: str,
    state: ServerState = Depends(get_state),
):
    return await trace_chat_service.prefetch_trace(run_id, state)


@router.post("/chat/{run_id}")
async def chat(run_id: str, req: ChatMessageRequest, state: ServerState = Depends(get_state)):
    try:
        return await trace_chat_service.chat_with_trace(
            run_id,
            req.message,
            [message.model_dump() for message in req.history],
            state,
        )
    except (BadRequestError, ResourceNotFoundError) as exc:
        return request_error_response(exc)


@router.post("/chat/{run_id}/abort", status_code=202)
async def abort_trace_chat(run_id: str, state: ServerState = Depends(get_state)):
    return await trace_chat_service.abort_trace_chat(run_id, state)
