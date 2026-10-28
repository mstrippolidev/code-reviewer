import logging

from pydantic import BaseModel
from redis.asyncio import Redis

from api.oauth.errors import InvalidGrantError
from api.oauth.pkce import verify_pkce_s256
from api.oauth.token_secrets import generate_secret, hash_secret

CODE_KEY_PREFIX = "oauth_code"

logger = logging.getLogger(__name__)


class AuthorizationCodeGrant(BaseModel):
    """What the user approved: stored under the code until the client redeems it."""

    user_id: int
    client_id: str
    redirect_uri: str
    code_challenge: str


class CodeRedemption(BaseModel):
    """What the client presents at the token endpoint."""

    client_id: str
    redirect_uri: str
    code_verifier: str


class AuthorizationCodeService:
    """Single-use authorization codes held in Redis, gone after their TTL or their first redemption."""

    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    async def issue(self, grant: AuthorizationCodeGrant) -> str:
        code = generate_secret()
        await self._redis.set(self._key(code), grant.model_dump_json(), ex=self._ttl_seconds)
        return code

    async def redeem(self, code: str, redemption: CodeRedemption) -> int:
        """Returns the user id the code was issued for.

        Raises:
            InvalidGrantError: If the code is unknown, expired, already used, or does not match the redemption.
        """
        stored = await self._redis.getdel(self._key(code))
        if stored is None:
            raise self._reject("unknown, expired or already used authorization code")
        grant = AuthorizationCodeGrant.model_validate_json(stored)
        if grant.client_id != redemption.client_id:
            raise self._reject("authorization code belongs to another client", grant)
        if grant.redirect_uri != redemption.redirect_uri:
            raise self._reject("redirect_uri differs from the authorization request", grant)
        self._require_pkce(grant, redemption)
        return grant.user_id

    def _require_pkce(self, grant: AuthorizationCodeGrant, redemption: CodeRedemption) -> None:
        try:
            verify_pkce_s256(redemption.code_verifier, grant.code_challenge)
        except InvalidGrantError as error:
            raise self._reject(str(error), grant) from error

    def _key(self, code: str) -> str:
        return f"{CODE_KEY_PREFIX}:{hash_secret(code)}"

    def _reject(self, reason: str, grant: AuthorizationCodeGrant | None = None) -> InvalidGrantError:
        user_id = grant.user_id if grant is not None else None
        client_id = grant.client_id if grant is not None else None
        logger.warning("OAuth code redemption rejected: %s (user_id=%s, client_id=%s)", reason, user_id, client_id)
        return InvalidGrantError(reason)
