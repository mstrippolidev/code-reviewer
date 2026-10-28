from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from api.dependencies import GUEST_SESSION_COOKIE, USER_SESSION_COOKIE

STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SESSION_COOKIES = frozenset({USER_SESSION_COOKIE, GUEST_SESSION_COOKIE})


class CookieOriginGuard:
    """Rejects state-changing requests that rely on a session cookie but come from an origin we don't serve.

    A browser attaches cookies to any request to our origin, even one a third-party page triggers, so
    SameSite=Lax is not the whole defense. Requests with an Authorization header are exempt: a page
    cannot add that header to a cross-site request on its own.
    """

    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]) -> None:
        self._app = app
        self._allowed_origins = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._is_forged(Request(scope)):
            response = JSONResponse({"detail": "Origin not allowed"}, status_code=403)
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)

    def _is_forged(self, request: Request) -> bool:
        if request.method not in STATE_CHANGING_METHODS:
            return False
        if "authorization" in request.headers:
            return False
        if SESSION_COOKIES.isdisjoint(request.cookies):
            return False
        return request.headers.get("origin") not in self._allowed_origins
