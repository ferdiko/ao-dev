"""Shared helpers for UI route modules."""

from fastapi.responses import JSONResponse

from sovara.server.database_manager import ResourceNotFoundError


def request_error_response(exc: Exception) -> JSONResponse:
    status_code = 404 if isinstance(exc, ResourceNotFoundError) else 400
    return JSONResponse(status_code=status_code, content={"error": str(exc)})
