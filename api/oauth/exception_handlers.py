from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from api.oauth.errors import AuthorizationRedirectError, OAuthProtocolError
from api.oauth.redirects import authorization_error_url

NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


async def handle_oauth_protocol_error(request: Request, error: OAuthProtocolError) -> JSONResponse:
    content = {"error": error.error, "error_description": error.description}
    return JSONResponse(status_code=error.status_code, content=content, headers=NO_STORE_HEADERS)


async def handle_authorization_redirect_error(request: Request, error: AuthorizationRedirectError) -> RedirectResponse:
    return RedirectResponse(authorization_error_url(error), status_code=302)


def register_oauth_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(OAuthProtocolError, handle_oauth_protocol_error)
    app.add_exception_handler(AuthorizationRedirectError, handle_authorization_redirect_error)
