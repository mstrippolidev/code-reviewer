from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.dependencies import get_frontend_base_url
from api.oauth.authorization_flow import AuthorizationDecision, AuthorizationFlow, AuthorizationParameters
from api.oauth.client_service import ClientRegistrationRequest, ClientRegistrationResponse, OAuthClientService
from api.oauth.dependencies import (
    get_authorization_flow,
    get_oauth_client_service,
    get_oauth_issuer,
    get_oauth_token_service,
    get_session_user_id,
    get_token_grant_handler,
    require_session_user_id,
)
from api.oauth.errors import AuthorizationRedirectError, InvalidRedirectUriError, OAuthProtocolError, UnknownClientError
from api.oauth.metadata import AuthorizationServerMetadata, build_authorization_server_metadata
from api.oauth.redirects import authorization_error_url
from api.oauth.token_grants import TokenGrantHandler, TokenRequest
from api.oauth.token_service import IssuedTokens, OAuthTokenService

router = APIRouter(tags=["OAuth"])


class ClientPublicInfo(BaseModel):
    client_id: str
    client_name: str


class AuthorizationDecisionResponse(BaseModel):
    redirect_to: str


@router.get("/.well-known/oauth-authorization-server")
async def read_authorization_server_metadata(issuer: str = Depends(get_oauth_issuer)) -> AuthorizationServerMetadata:
    """Discovery document (RFC 8414): where this server's OAuth endpoints are and what they support.

    An MCP client reads this first to find the authorize, token, registration and revocation URLs.
    """
    return build_authorization_server_metadata(issuer)


@router.post("/oauth/register", status_code=201)
async def register_client(
    payload: ClientRegistrationRequest,
    clients: OAuthClientService = Depends(get_oauth_client_service),
) -> ClientRegistrationResponse:
    """Dynamic client registration (RFC 7591): an app announces its name and redirect URIs and gets a client_id.

    Open to any caller. Redirect URIs must be https, http on loopback, or a private-use scheme.
    """
    try:
        client = await clients.register(payload)
    except InvalidRedirectUriError as error:
        raise OAuthProtocolError("invalid_redirect_uri", str(error)) from error
    return ClientRegistrationResponse(
        client_id=client.client_id, client_name=client.client_name, redirect_uris=client.redirect_uris
    )


@router.get("/oauth/clients/{client_id}")
async def read_client(
    client_id: str, clients: OAuthClientService = Depends(get_oauth_client_service)
) -> ClientPublicInfo:
    """Public name of a registered client, so the consent page can say who is asking for access."""
    try:
        client = await clients.get(client_id)
    except UnknownClientError as error:
        raise OAuthProtocolError("invalid_client", "Unknown client_id", status_code=404) from error
    return ClientPublicInfo(client_id=client.client_id, client_name=client.client_name)


@router.get("/oauth/authorize")
async def authorize(
    request: Request,
    parameters: Annotated[AuthorizationParameters, Query()],
    user_id: int | None = Depends(get_session_user_id),
    flow: AuthorizationFlow = Depends(get_authorization_flow),
    frontend_base_url: str = Depends(get_frontend_base_url),
) -> RedirectResponse:
    """Where the browser lands when a client asks for access (authorization code flow with PKCE).

    No web session: sends the user through GitHub login and back here. A client the user already approved
    gets its code immediately; a new client sends the user to the consent page.
    """
    validated = await flow.validate(parameters)
    if user_id is None:
        return RedirectResponse(_github_login_url(request.url.query), status_code=302)
    if await flow.is_approved(validated, user_id):
        return RedirectResponse(await flow.grant(validated, user_id), status_code=302)
    return RedirectResponse(f"{frontend_base_url}/consent?{request.url.query}", status_code=302)


@router.post("/oauth/authorize/decision")
async def decide_authorization(
    decision: AuthorizationDecision,
    user_id: int = Depends(require_session_user_id),
    flow: AuthorizationFlow = Depends(get_authorization_flow),
) -> AuthorizationDecisionResponse:
    """The consent page's Approve or Deny. Returns the URL the browser must go to next.

    Needs the web session cookie; an OAuth access token cannot approve clients. Approving remembers the
    client for this user, so reconnecting it skips the consent page.
    """
    try:
        validated = await flow.validate(decision)
    except AuthorizationRedirectError as error:
        return AuthorizationDecisionResponse(redirect_to=authorization_error_url(error))
    if not decision.approve:
        return AuthorizationDecisionResponse(redirect_to=flow.denial_url(validated))
    await flow.remember_approval(validated, user_id)
    return AuthorizationDecisionResponse(redirect_to=await flow.grant(validated, user_id))


@router.post("/oauth/token")
async def issue_token(
    form: Annotated[TokenRequest, Form()],
    response: Response,
    handler: TokenGrantHandler = Depends(get_token_grant_handler),
) -> IssuedTokens:
    """Trades an authorization code (with its PKCE verifier) or a refresh token for a new access and refresh token.

    Form-encoded. Every failure to redeem a grant is the same `invalid_grant`.
    """
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return await handler.handle(form)


@router.post("/oauth/revoke")
async def revoke_token(
    token: Annotated[str | None, Form()] = None,
    tokens: OAuthTokenService = Depends(get_oauth_token_service),
) -> dict[str, str]:
    """Revokes an access or refresh token (RFC 7009) together with every token from the same authorization.

    Answers 200 for an unknown token too, so callers cannot probe which tokens exist.
    """
    if not token:
        raise OAuthProtocolError("invalid_request", "token is required")
    await tokens.revoke(token)
    return {}


def _github_login_url(authorize_query: str) -> str:
    return "/api/oauth/github/login?" + urlencode({"return_to": f"/oauth/authorize?{authorize_query}"})
