"""Trace chat orchestration and persistence helpers."""

from fastapi import HTTPException

from sovara.server.database import DB
from sovara.server.state import ServerState, logger

TRACE_CHAT_CANCELED_DETAIL = "Trace chat canceled"
TRACE_CHAT_TIMEOUT_SECONDS = 120.0


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


def get_trace_chat_history(run_id: str) -> list[dict]:
    return DB.get_trace_chat_history(run_id)


def update_trace_chat_history(run_id: str, history: list[dict]) -> list[dict]:
    DB.update_trace_chat_history(run_id, history)
    return DB.get_trace_chat_history(run_id)


def clear_trace_chat_history(run_id: str) -> None:
    DB.clear_trace_chat_history(run_id)


async def prefetch_trace(run_id: str, state: ServerState) -> dict[str, str]:
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


async def chat_with_trace(
    run_id: str,
    message: str,
    history: list[dict],
    state: ServerState,
) -> dict:
    import httpx

    from sovara.common.constants import HOST, INFERENCE_PORT

    generation = state.begin_trace_chat_request(run_id)
    persisted_history = [*history, {"role": "user", "content": message}]

    def is_cancelled_or_stale() -> bool:
        return (
            state.is_trace_chat_request_cancelled(run_id, generation)
            or not state.is_trace_chat_request_current(run_id, generation)
        )

    async def request_answer() -> dict:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"http://{HOST}:{INFERENCE_PORT}/chat/{run_id}",
                    json={"message": message, "history": history},
                    timeout=TRACE_CHAT_TIMEOUT_SECONDS,
                )
        except httpx.TimeoutException:
            if is_cancelled_or_stale():
                raise HTTPException(409, TRACE_CHAT_CANCELED_DETAIL) from None
            logger.error("Trace chat proxy timed out after %.1fs for run %s", TRACE_CHAT_TIMEOUT_SECONDS, run_id)
            raise HTTPException(
                504,
                f"Trace chat timed out after {int(TRACE_CHAT_TIMEOUT_SECONDS)} seconds",
            ) from None
        except httpx.HTTPError as exc:
            if is_cancelled_or_stale():
                raise HTTPException(409, TRACE_CHAT_CANCELED_DETAIL) from None
            logger.error("Trace chat proxy failed for run %s: %s", run_id, exc)
            raise HTTPException(502, "Could not reach inference server") from exc

        if resp.status_code != 200:
            detail = _extract_http_error_detail(resp)
            if is_cancelled_or_stale() or detail == TRACE_CHAT_CANCELED_DETAIL:
                raise HTTPException(409, TRACE_CHAT_CANCELED_DETAIL)
            raise HTTPException(resp.status_code, detail)

        try:
            return resp.json()
        except ValueError as exc:
            logger.error("Inference server returned invalid JSON for run %s", run_id)
            raise HTTPException(502, "Invalid response from inference server") from exc

    try:
        update_trace_chat_history(run_id, persisted_history)
        data = await request_answer()

        if is_cancelled_or_stale():
            raise HTTPException(409, TRACE_CHAT_CANCELED_DETAIL)

        answer = data.get("answer")
        if isinstance(answer, str):
            update_trace_chat_history(
                run_id,
                persisted_history + [{"role": "assistant", "content": answer}],
            )

        return {
            **data,
            "history": get_trace_chat_history(run_id),
        }
    finally:
        state.finish_trace_chat_request(run_id, generation)


async def abort_trace_chat(run_id: str, state: ServerState) -> dict[str, str]:
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
