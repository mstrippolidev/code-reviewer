"""
    In-memory stand-ins shared by the OAuth tests: a clock, a token repository, Redis and a DB session.
"""
import uuid
from datetime import datetime, timedelta

from api.db.models.oauth_client import OAuthClient
from api.db.models.oauth_token import OAuthToken

START = datetime(2026, 1, 1, 12, 0, 0)


class FakeClock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class FakeTokenRepository:
    def __init__(self) -> None:
        self.rows: list[OAuthToken] = []
        self.commits = 0
        self.lose_the_race = False

    def add(self, token: OAuthToken) -> None:
        token.id = len(self.rows) + 1
        self.rows.append(token)

    async def find_by_access_hash(self, access_token_hash: str) -> OAuthToken | None:
        return next((row for row in self.rows if row.access_token_hash == access_token_hash), None)

    async def find_by_refresh_hash(self, refresh_token_hash: str) -> OAuthToken | None:
        return next((row for row in self.rows if row.refresh_token_hash == refresh_token_hash), None)

    async def mark_refresh_used(self, token_id: int, used_at: datetime) -> bool:
        row = self.rows[token_id - 1]
        if self.lose_the_race or row.refresh_used_at is not None:
            return False
        row.refresh_used_at = used_at
        return True

    async def revoke_family(self, family_id: uuid.UUID, revoked_at: datetime) -> None:
        for row in self.rows:
            if row.family_id == family_id and row.revoked_at is None:
                row.revoked_at = revoked_at

    async def commit(self) -> None:
        self.commits += 1


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    async def set(self, key: str, value: str, ex: int) -> None:
        self.values[key] = value
        self.expiries[key] = ex

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)


class FakeOAuthSession:
    """Covers only the calls OAuthClientService makes."""

    def __init__(self) -> None:
        self.clients: dict[str, OAuthClient] = {}
        self.consents: set[tuple[int, str]] = set()
        self.commits = 0

    def add(self, client: OAuthClient) -> None:
        self.clients[client.client_id] = client

    async def commit(self) -> None:
        self.commits += 1

    async def get(self, _model: type[OAuthClient], client_id: str) -> OAuthClient | None:
        return self.clients.get(client_id)

    async def scalar(self, statement) -> int | None:
        user_id, client_id = statement.compile().params.values()
        return 1 if (user_id, client_id) in self.consents else None

    async def execute(self, statement) -> None:
        values = statement.compile().params
        self.consents.add((values["user_id"], values["client_id"]))
