import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from api.repos.errors import (
    BranchNotFoundError,
    GitHubAuthorizationExpiredError,
    GitHubVerificationUnavailableError,
    IndexedFileNotFoundError,
    InsufficientPythonError,
    NotRepoOwnerError,
    RepoAlreadyRegisteredError,
    RepoEventPublishError,
    RepoIdMismatchError,
    RepoNotFoundError,
    RepoPurgeError,
)

logger = logging.getLogger(__name__)

REPO_ERROR_STATUS_CODES: dict[type[Exception], int] = {
    RepoAlreadyRegisteredError: status.HTTP_409_CONFLICT,
    RepoNotFoundError: status.HTTP_404_NOT_FOUND,
    IndexedFileNotFoundError: status.HTTP_404_NOT_FOUND,
    RepoIdMismatchError: status.HTTP_400_BAD_REQUEST,
    InsufficientPythonError: status.HTTP_400_BAD_REQUEST,
    BranchNotFoundError: status.HTTP_400_BAD_REQUEST,
    NotRepoOwnerError: status.HTTP_403_FORBIDDEN,
    GitHubAuthorizationExpiredError: status.HTTP_401_UNAUTHORIZED,
    GitHubVerificationUnavailableError: status.HTTP_502_BAD_GATEWAY,
    RepoEventPublishError: status.HTTP_502_BAD_GATEWAY,
    RepoPurgeError: status.HTTP_502_BAD_GATEWAY,
}


class ErrorMessageHandler:
    """Answers a domain error with a fixed status code and the error's own client-facing message."""

    def __init__(self, status_code: int) -> None:
        self._status_code = status_code

    async def __call__(self, request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(status_code=self._status_code, content={"detail": str(error)})


async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=error)
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred"})


def register_repo_exception_handlers(app: FastAPI) -> None:
    for error_type, status_code in REPO_ERROR_STATUS_CODES.items():
        app.add_exception_handler(error_type, ErrorMessageHandler(status_code))


def register_exception_handlers(app: FastAPI) -> None:
    register_repo_exception_handlers(app)
    app.add_exception_handler(Exception, handle_unexpected_error)
