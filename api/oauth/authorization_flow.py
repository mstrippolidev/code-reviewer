import re
from dataclasses import dataclass

from pydantic import BaseModel

from api.db.models.oauth_client import OAuthClient
from api.oauth.authorization_code_service import AuthorizationCodeGrant, AuthorizationCodeService
from api.oauth.client_service import OAuthClientService
from api.oauth.errors import AuthorizationRedirectError, InvalidRedirectUriError, OAuthProtocolError, UnknownClientError
from api.oauth.redirect_uri import redirect_uri_matches
from api.oauth.redirects import append_query, authorization_error_url

S256_CHALLENGE_PATTERN = re.compile(r"[A-Za-z0-9_\-]{43}")


class AuthorizationParameters(BaseModel):
    """The query of an authorize request, every field optional so a missing one is answered as an OAuth error."""

    response_type: str | None = None
    client_id: str | None = None
    redirect_uri: str | None = None
    code_challenge: str | None = None
    code_challenge_method: str | None = None
    state: str | None = None


class AuthorizationDecision(AuthorizationParameters):
    approve: bool


@dataclass(frozen=True)
class ValidatedAuthorization:
    client_id: str
    client_name: str
    redirect_uri: str
    code_challenge: str
    state: str | None


class AuthorizationFlow:
    """Validates authorize requests and turns an approval into a redirect carrying a single-use code."""

    def __init__(self, clients: OAuthClientService, codes: AuthorizationCodeService) -> None:
        self._clients = clients
        self._codes = codes

    async def validate(self, parameters: AuthorizationParameters) -> ValidatedAuthorization:
        """Raises OAuthProtocolError when the client or redirect URI cannot be trusted (never redirect then),
        and AuthorizationRedirectError for any other problem (redirect it back to the client)."""
        client = await self._require_trusted_client(parameters)
        self._require_valid_request(parameters)
        return ValidatedAuthorization(
            client_id=client.client_id,
            client_name=client.client_name,
            redirect_uri=parameters.redirect_uri,
            code_challenge=parameters.code_challenge,
            state=parameters.state,
        )

    async def is_approved(self, validated: ValidatedAuthorization, user_id: int) -> bool:
        return await self._clients.has_consent(user_id, validated.client_id)

    async def remember_approval(self, validated: ValidatedAuthorization, user_id: int) -> None:
        await self._clients.record_consent(user_id, validated.client_id)

    async def grant(self, validated: ValidatedAuthorization, user_id: int) -> str:
        """Returns the client's redirect URL carrying a fresh authorization code."""
        grant = AuthorizationCodeGrant(
            user_id=user_id,
            client_id=validated.client_id,
            redirect_uri=validated.redirect_uri,
            code_challenge=validated.code_challenge,
        )
        params = {"code": await self._codes.issue(grant)}
        if validated.state is not None:
            params["state"] = validated.state
        return append_query(validated.redirect_uri, params)

    def denial_url(self, validated: ValidatedAuthorization) -> str:
        denial = AuthorizationRedirectError(
            validated.redirect_uri, "access_denied", "The user denied the request", validated.state
        )
        return authorization_error_url(denial)

    async def _require_trusted_client(self, parameters: AuthorizationParameters) -> OAuthClient:
        if not parameters.client_id or not parameters.redirect_uri:
            raise OAuthProtocolError("invalid_request", "client_id and redirect_uri are required")
        try:
            client = await self._clients.get(parameters.client_id)
            registered = redirect_uri_matches(client.redirect_uris, parameters.redirect_uri)
        except (UnknownClientError, InvalidRedirectUriError) as error:
            raise OAuthProtocolError("invalid_request", "Unknown client or malformed redirect_uri") from error
        if not registered:
            raise OAuthProtocolError("invalid_request", "redirect_uri is not registered for this client")
        return client

    def _require_valid_request(self, parameters: AuthorizationParameters) -> None:
        problem = self._find_problem(parameters)
        if problem is not None:
            error, description = problem
            raise AuthorizationRedirectError(parameters.redirect_uri, error, description, parameters.state)

    def _find_problem(self, parameters: AuthorizationParameters) -> tuple[str, str] | None:
        if parameters.response_type != "code":
            return "unsupported_response_type", "response_type must be code"
        if parameters.code_challenge_method != "S256":
            return "invalid_request", "code_challenge_method must be S256"
        if not parameters.code_challenge or not S256_CHALLENGE_PATTERN.fullmatch(parameters.code_challenge):
            return "invalid_request", "code_challenge must be a 43-character S256 challenge"
        return None
