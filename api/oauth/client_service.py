from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.oauth_client import OAuthClient
from api.db.models.oauth_consent import OAuthConsent
from api.oauth.errors import UnknownClientError
from api.oauth.redirect_uri import validate_redirect_uri
from api.oauth.token_secrets import generate_secret

MAX_REDIRECT_URIS = 5
GRANT_TYPES = ["authorization_code", "refresh_token"]


class ClientRegistrationRequest(BaseModel):
    """The RFC 7591 fields we act on; any others the client sends are ignored."""

    model_config = ConfigDict(extra="ignore")

    client_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    redirect_uris: Annotated[list[str], Field(min_length=1, max_length=MAX_REDIRECT_URIS)]


class ClientRegistrationResponse(BaseModel):
    client_id: str
    client_name: str
    redirect_uris: list[str]
    token_endpoint_auth_method: str = "none"
    grant_types: list[str] = GRANT_TYPES
    response_types: list[str] = ["code"]


class OAuthClientService:
    """Registers OAuth clients and remembers which clients a user has approved."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(self, request: ClientRegistrationRequest) -> OAuthClient:
        """Raises InvalidRedirectUriError if any redirect URI is not allowed."""
        for uri in request.redirect_uris:
            validate_redirect_uri(uri)
        client = OAuthClient(
            client_id=generate_secret(),
            client_name=request.client_name,
            redirect_uris=list(dict.fromkeys(request.redirect_uris)),
        )
        self._session.add(client)
        await self._session.commit()
        return client

    async def get(self, client_id: str) -> OAuthClient:
        client = await self._session.get(OAuthClient, client_id)
        if client is None:
            raise UnknownClientError(f"Unknown client_id {client_id}")
        return client

    async def has_consent(self, user_id: int, client_id: str) -> bool:
        statement = select(OAuthConsent.id).where(OAuthConsent.user_id == user_id, OAuthConsent.client_id == client_id)
        return await self._session.scalar(statement) is not None

    async def record_consent(self, user_id: int, client_id: str) -> None:
        statement = (
            insert(OAuthConsent)
            .values(user_id=user_id, client_id=client_id)
            .on_conflict_do_nothing(index_elements=["user_id", "client_id"])
        )
        await self._session.execute(statement)
        await self._session.commit()
