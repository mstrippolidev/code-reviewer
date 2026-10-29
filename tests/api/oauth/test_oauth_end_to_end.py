"""
    The whole OAuth flow over the real routes, real Postgres and real Redis, through an in-process ASGI client.

    It commits a user and a client, so it deletes them afterwards (tokens and consents cascade). Run with
    `-m "db and redis"`; requires the migrations applied and Redis running.
"""
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from redis.asyncio import Redis
from sqlalchemy import delete, select

from api.config.settings import get_api_settings
from api.db.engine import DatabaseEngine
from api.db.models.oauth_client import OAuthClient
from api.db.models.oauth_token import OAuthToken
from api.db.models.user import User
from api.dependencies import USER_SESSION_COOKIE, get_current_user, get_jwt_service
from api.oauth.exception_handlers import register_oauth_exception_handlers
from api.routers.oauth import router as oauth_router

pytestmark = [pytest.mark.db, pytest.mark.redis, pytest.mark.asyncio]

USER_GITHUB_ID = 950_000_001
CLIENT_NAME = "E2E Test Client"
REDIRECT_URI = "http://localhost:53682/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


@pytest_asyncio.fixture
async def app() -> AsyncIterator[FastAPI]:
    settings = get_api_settings()
    application = FastAPI()
    application.include_router(oauth_router)
    register_oauth_exception_handlers(application)

    @application.get("/whoami")
    async def whoami(user: User = Depends(get_current_user)) -> dict[str, int]:
        return {"user_id": user.id}

    application.state.database_engine = DatabaseEngine(settings.async_database_url)
    application.state.redis = Redis.from_url(settings.redis_url)

    yield application

    async with application.state.database_engine.new_session() as session:
        await session.execute(delete(User).where(User.github_id == USER_GITHUB_ID))
        await session.execute(delete(OAuthClient).where(OAuthClient.client_name == CLIENT_NAME))
        await session.commit()
    await application.state.redis.aclose()
    await application.state.database_engine.dispose()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.state.database_engine.new_session() as session:
        user = User(
            github_id=USER_GITHUB_ID,
            github_username="oauth-e2e-test",
            encrypted_github_token="unused",
            github_granted_scopes="repo",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    session_cookie = get_jwt_service().issue_user_session_token(user_id=user.id)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as http_client:
        http_client.cookies.set(USER_SESSION_COOKIE, session_cookie)
        yield http_client


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def _authorize_params(client_id: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "xyz",
    }


async def _token(client: httpx.AsyncClient, **form: str) -> httpx.Response:
    return await client.post("/oauth/token", data=form)


async def test_register_consent_exchange_refresh_and_reuse_detection(client: httpx.AsyncClient, app: FastAPI) -> None:
    registration = await client.post("/oauth/register", json={"client_name": CLIENT_NAME, "redirect_uris": [REDIRECT_URI]})
    client_id = registration.json()["client_id"]
    params = _authorize_params(client_id)

    first_visit = await client.get("/oauth/authorize", params=params)
    assert urlsplit(first_visit.headers["location"]).path == "/consent"

    decision = await client.post("/oauth/authorize/decision", json=params | {"approve": True})
    code = _query(decision.json()["redirect_to"])["code"][0]

    second_visit = await client.get("/oauth/authorize", params=params)
    assert _query(second_visit.headers["location"])["code"][0] != code

    exchange_form = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": VERIFIER,
    }
    issued = await _token(client, **exchange_form)
    assert issued.status_code == 200
    tokens = issued.json()
    assert (await _token(client, **exchange_form)).json()["error"] == "invalid_grant"

    async with app.state.database_engine.new_session() as session:
        [row] = (await session.scalars(select(OAuthToken).where(OAuthToken.client_id == client_id))).all()
    assert tokens["access_token"] not in (row.access_token_hash, row.refresh_token_hash)
    assert tokens["refresh_token"] not in (row.access_token_hash, row.refresh_token_hash)

    refreshed = await _token(client, grant_type="refresh_token", client_id=client_id, refresh_token=tokens["refresh_token"])
    assert refreshed.status_code == 200
    successor = refreshed.json()

    replay = await _token(client, grant_type="refresh_token", client_id=client_id, refresh_token=tokens["refresh_token"])
    assert replay.json()["error"] == "invalid_grant"
    after_replay = await _token(
        client, grant_type="refresh_token", client_id=client_id, refresh_token=successor["refresh_token"]
    )
    assert after_replay.json()["error"] == "invalid_grant"

    async with app.state.database_engine.new_session() as session:
        rows = (await session.scalars(select(OAuthToken).where(OAuthToken.client_id == client_id))).all()
    assert len(rows) == 2
    assert all(token_row.revoked_at is not None for token_row in rows)


async def _issue_tokens(client: httpx.AsyncClient) -> dict[str, str]:
    registration = await client.post("/oauth/register", json={"client_name": CLIENT_NAME, "redirect_uris": [REDIRECT_URI]})
    client_id = registration.json()["client_id"]
    params = _authorize_params(client_id)
    decision = await client.post("/oauth/authorize/decision", json=params | {"approve": True})
    code = _query(decision.json()["redirect_to"])["code"][0]
    issued = await _token(
        client,
        grant_type="authorization_code",
        client_id=client_id,
        code=code,
        redirect_uri=REDIRECT_URI,
        code_verifier=VERIFIER,
    )
    return issued.json()


async def _stored_user_id(app: FastAPI) -> int:
    async with app.state.database_engine.new_session() as session:
        return await session.scalar(select(User.id).where(User.github_id == USER_GITHUB_ID))


def _cookieless_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_an_issued_access_token_authenticates_a_protected_route_until_it_is_revoked(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    tokens = await _issue_tokens(client)
    user_id = await _stored_user_id(app)
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}

    async with _cookieless_client(app) as anonymous:
        assert (await anonymous.get("/whoami")).status_code == 401

        authorized = await anonymous.get("/whoami", headers=bearer)
        assert authorized.status_code == 200
        assert authorized.json() == {"user_id": user_id}

        refresh_as_bearer = {"Authorization": f"Bearer {tokens['refresh_token']}"}
        assert (await anonymous.get("/whoami", headers=refresh_as_bearer)).status_code == 401

        assert (await anonymous.post("/oauth/revoke", data={"token": tokens["access_token"]})).status_code == 200
        assert (await anonymous.get("/whoami", headers=bearer)).status_code == 401
