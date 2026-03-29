"""Simple SSE event bus for priors backend mutations."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from starlette.responses import StreamingResponse

_subscribers: list[asyncio.Queue] = []
KEEPALIVE_INTERVAL = 30


def publish(event_type: str, data: dict[str, Any]) -> None:
    for queue in list(_subscribers):
        try:
            queue.put_nowait((event_type, data))
        except asyncio.QueueFull:
            pass


async def _event_stream(queue: asyncio.Queue) -> AsyncIterator[str]:
    try:
        while True:
            try:
                event_type, data = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL)
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        if queue in _subscribers:
            _subscribers.remove(queue)


async def subscribe() -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    _subscribers.append(queue)
    return StreamingResponse(
        _event_stream(queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
