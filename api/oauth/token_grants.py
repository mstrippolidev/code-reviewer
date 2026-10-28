from pydantic import BaseModel

from api.oauth.authorization_code_service import AuthorizationCodeService, CodeRedemption
from api.oauth.client_service import OAuthClientService
from api.oauth.errors import InvalidGrantError, OAuthProtocolError, UnknownClientError
from api.oauth.token_service import IssuedTokens, OAuthTokenService


class TokenRequest(BaseModel):
    """The form of a token request, every field optional so a missing one is answered as an OAuth error."""

    grant_type: str | None = None
    client_id: str | None = None
    code: str | None = None
    redirect_uri: str | None = None
    code_verifier: str | None = None
    refresh_token: str | None = None


class TokenGrantHandler:
    """Answers a token request by redeeming an authorization code or rotating a refresh token."""

    def __init__(
        self, clients: OAuthClientService, codes: AuthorizationCodeService, tokens: OAuthTokenService
    ) -> None:
        self._clients = clients
        self._codes = codes
        self._tokens = tokens

    async def handle(self, request: TokenRequest) -> IssuedTokens:
        """Raises OAuthProtocolError for every way the request can be refused."""
        client_id = self._require(request.client_id, "client_id")
        await self._require_registered(client_id)
        try:
            if request.grant_type == "authorization_code":
                return await self._exchange_code(request, client_id)
            if request.grant_type == "refresh_token":
                return await self._tokens.refresh(self._require(request.refresh_token, "refresh_token"), client_id)
        except InvalidGrantError as error:
            raise OAuthProtocolError("invalid_grant", "The grant is invalid, expired or revoked") from error
        raise OAuthProtocolError("unsupported_grant_type", "grant_type must be authorization_code or refresh_token")

    async def _exchange_code(self, request: TokenRequest, client_id: str) -> IssuedTokens:
        redemption = CodeRedemption(
            client_id=client_id,
            redirect_uri=self._require(request.redirect_uri, "redirect_uri"),
            code_verifier=self._require(request.code_verifier, "code_verifier"),
        )
        user_id = await self._codes.redeem(self._require(request.code, "code"), redemption)
        return await self._tokens.issue(user_id, client_id)

    async def _require_registered(self, client_id: str) -> None:
        try:
            await self._clients.get(client_id)
        except UnknownClientError as error:
            raise OAuthProtocolError("invalid_client", "Unknown client_id", status_code=401) from error

    def _require(self, value: str | None, name: str) -> str:
        if not value:
            raise OAuthProtocolError("invalid_request", f"{name} is required")
        return value
