"""
FastAPI application factory.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from sovara.common.logger import create_file_logger
from sovara.common.constants import MAIN_SERVER_LOG
from sovara.server.state import ServerState

logger = create_file_logger(MAIN_SERVER_LOG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize server state, start background tasks, clean up on shutdown."""
    state = ServerState()
    state._loop = asyncio.get_running_loop()
    app.state.server_state = state

    # Wire up uvicorn server reference for clean shutdown (set by so_server.py)
    uv_server = getattr(app.state, "uvicorn_server", None)
    if uv_server:
        state._uvicorn_server = uv_server

    # Load finished runs from DB
    state.load_finished_runs()

    # Start inactivity monitor
    async def inactivity_monitor():
        while True:
            await asyncio.sleep(60)
            if state.check_inactivity():
                logger.info("Inactivity timeout reached, shutting down...")
                state.request_shutdown()
                return

    monitor_task = asyncio.create_task(inactivity_monitor())

    logger.info("Server ready")
    yield

    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    from sovara.server.routes.runner import router as runner_router
    from sovara.server.routes.ui import router as ui_router
    from sovara.server.routes.events import router as events_router

    app.include_router(runner_router)
    app.include_router(ui_router)
    app.include_router(events_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def get_state(request: Request) -> ServerState:
    """FastAPI dependency to get server state."""
    return request.app.state.server_state
