import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=error)
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred"})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Exception, handle_unexpected_error)
