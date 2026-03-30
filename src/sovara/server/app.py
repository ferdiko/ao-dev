"""
FastAPI application factory.
"""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from sovara.common.logger import create_file_logger
from sovara.common.constants import MAIN_SERVER_LOG, MAIN_SERVER_STARTUP_LOCK
from sovara.server.state import ServerState
from sovara.server.graph_analysis import inference_server
from sovara.server.priors_backend import server as priors_backend_server

logger = create_file_logger(MAIN_SERVER_LOG)


def _clear_startup_lock() -> None:
    try:
        os.remove(MAIN_SERVER_STARTUP_LOCK)
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("Could not remove startup lock %s: %s", MAIN_SERVER_STARTUP_LOCK, exc)


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

    # Start child sub-servers
    priors_backend_server.start()
    inference_server.start()

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
    _clear_startup_lock()
    yield

    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass

    inference_server.stop()
    priors_backend_server.stop()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def touch_server_activity(request: Request, call_next):
        state = getattr(request.app.state, "server_state", None)
        if state is not None:
            state.touch_activity()
        return await call_next(request)

    from sovara.server.routes.runner import router as runner_router
    from sovara.server.routes.ui import router as ui_router
    from sovara.server.routes.events import router as events_router
    from sovara.server.routes.internal import router as internal_router

    app.include_router(runner_router)
    app.include_router(ui_router)
    app.include_router(events_router)
    app.include_router(internal_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def get_state(request: Request) -> ServerState:
    """FastAPI dependency to get server state."""
    return request.app.state.server_state
