"""FastAPI app for the priors backend child service."""

import asyncio
import time

from fastapi import FastAPI, Request
from starlette.responses import StreamingResponse

from sovara.server.priors_backend.events import subscribe
from sovara.server.priors_backend.logger import logger
from sovara.server.priors_backend.routes import router as priors_router


_last_activity_time = time.time()


def update_activity() -> None:
    global _last_activity_time
    _last_activity_time = time.time()


class ScopeMiddleware:
    """Track activity and attach trusted priors scope from request headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            update_activity()
            state = scope.setdefault("state", {})
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope.get("headers", [])
            }
            user_id = headers.get("x-sovara-user-id")
            project_id = headers.get("x-sovara-project-id")
            if not user_id:
                user_id = "local"
            if not project_id:
                project_id = "default"
            state["user_id"] = user_id
            state["project_id"] = project_id
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ScopeMiddleware)

    app.include_router(priors_router)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "priors_backend"}

    @app.get("/api/v1/info")
    def info():
        return {
            "status": "bootstrapped",
            "service": "priors_backend",
            "message": "Priors backend routes are being migrated into ao-dev.",
        }

    @app.get("/api/v1/events")
    async def events(request: Request):
        return await subscribe()

    @app.get("/")
    def root():
        return {
            "service": "priors_backend",
            "version": "0.0.1",
        }

    logger.info("Initialized in-repo priors backend app")

    return app
