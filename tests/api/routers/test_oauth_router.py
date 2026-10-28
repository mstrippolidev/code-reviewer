"""
    Tests for the /oauth/* routes with the real services over in-memory fakes: no DB, no Redis.

    Tokens and cookies are really signed and verified; the PKCE values are the RFC 7636 example.
"""
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import USER_SESSION_COOKIE, get_frontend_base_url, get_jwt_service
from api.oauth.authorization_code_service import AuthorizationCodeService
from api.oauth.client_service import OAuthClientService
from api.oauth.dependencies import (
    get_authorization_code_service,
    get_oauth_client_service,
    get_oauth_issuer,
    get_oauth_token_service,
)
from api.oauth.exception_handlers import register_oauth_exception_handlers
from api.oauth.token_service import OAuthTokenService, TokenLifetimes
from api.routers.oauth import router as oauth_router
from api.security.jwt_service import JwtTokenService
from tests.api.oauth.fakes import FakeClock, FakeOAuthSession, FakeRedis, FakeTokenRepository

FRONTEND_URL = "http://localhost:5173"
REDIRECT_URI = "http://localhost:53682/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
USER_ID = 7
LIFETIMES = TokenLifetimes(access_seconds=3600, refresh_idle_seconds=7 * 86400, refresh_absolute_seconds=30 * 86400)
JWT_SERVICE = JwtTokenService(
    secret_key="oauth-router-test-secret-key-32-bytes", access_token_ttl_seconds=3600, state_token_ttl_seconds=300
)


@dataclass
class Harness:
    client: TestClient
    session: FakeOAuthSession
    redis: FakeRedis
    repository: FakeTokenRepository


@pytest.fixture
def harness() -> Harness:
    app = FastAPI()
    app.include_router(oauth_router)
    register_oauth_exception_handlers(app)
    session, redis, repository = FakeOAuthSession(), FakeRedis(), FakeTokenRepository()
    clients = OAuthClientService(session)
    codes = AuthorizationCodeService(redis, 60)
    tokens = OAuthTokenService(repository, LIFETIMES, FakeClock())
    app.dependency_overrides[get_oauth_client_service] = lambda: clients
    app.dependency_overrides[get_authorization_code_service] = lambda: codes
    app.dependency_overrides[get_oauth_token_service] = lambda: tokens
    app.dependency_overrides[get_jwt_service] = lambda: JWT_SERVICE
    app.dependency_overrides[get_frontend_base_url] = lambda: FRONTEND_URL
    app.dependency_overrides[get_oauth_issuer] = lambda: "http://api.test"
    return Harness(TestClient(app, follow_redirects=False), session, redis, repository)


def _register(harness: Harness, redirect_uris: list[str] | None = None) -> str:
    response = harness.client.post(
        "/oauth/register", json={"client_name": "Claude Code", "redirect_uris": redirect_uris or [REDIRECT_URI]}
    )
    return response.json()["client_id"]


def _log_in(harness: Harness, user_id: int = USER_ID) -> None:
    harness.client.cookies.set(USER_SESSION_COOKIE, JWT_SERVICE.issue_user_session_token(user_id=user_id))


def _authorize_params(client_id: str, **overrides: str | None) -> dict[str, str]:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "xyz",
    } | overrides
    return {name: value for name, value in params.items() if value is not None}


def _authorize(harness: Harness, client_id: str, **overrides: str | None):
    return harness.client.get("/oauth/authorize", params=_authorize_params(client_id, **overrides))


def _decide(harness: Harness, client_id: str, approve: bool, **overrides: str | None):
    return harness.client.post(
        "/oauth/authorize/decision", json=_authorize_params(client_id, **overrides) | {"approve": approve}
    )


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def _obtain_code(harness: Harness, client_id: str) -> str:
    _log_in(harness)
    return _query(_decide(harness, client_id, approve=True).json()["redirect_to"])["code"][0]


def _exchange(harness: Harness, client_id: str, code: str, **overrides: str):
    form = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": VERIFIER,
    } | overrides
    return harness.client.post("/oauth/token", data=form)


def _obtain_tokens(harness: Harness, client_id: str) -> dict:
    return _exchange(harness, client_id, _obtain_code(harness, client_id)).json()


def _refresh(harness: Harness, client_id: str, refresh_token: str):
    return harness.client.post(
        "/oauth/token", data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh_token}
    )


# ---- registration ----------------------------------------------------------------------------


def test_registering_a_client_answers_201_with_its_id_and_public_client_settings(harness: Harness) -> None:
    response = harness.client.post(
        "/oauth/register", json={"client_name": "Cursor", "redirect_uris": [REDIRECT_URI], "ignored": "x"}
    )

    body = response.json()
    assert response.status_code == 201
    assert body["client_name"] == "Cursor"
    assert body["redirect_uris"] == [REDIRECT_URI]
    assert body["token_endpoint_auth_method"] == "none"
    assert body["client_id"] in harness.session.clients
    assert "client_secret" not in body


@pytest.mark.parametrize("uri", ["http://app.example.com/cb", "javascript:alert(1)", "/relative", "https://x/cb#frag"])
def test_registering_with_a_disallowed_redirect_uri_answers_invalid_redirect_uri(harness: Harness, uri: str) -> None:
    response = harness.client.post("/oauth/register", json={"client_name": "Evil", "redirect_uris": [uri]})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"
    assert harness.session.clients == {}


@pytest.mark.parametrize("uri", ["https://app.example.com/cb", "cursor://app/callback", "http://127.0.0.1:9/cb"])
def test_registering_with_an_allowed_redirect_uri_works(harness: Harness, uri: str) -> None:
    response = harness.client.post("/oauth/register", json={"client_name": "App", "redirect_uris": [uri]})

    assert response.status_code == 201


def test_registering_without_redirect_uris_is_rejected(harness: Harness) -> None:
    assert harness.client.post("/oauth/register", json={"client_name": "App", "redirect_uris": []}).status_code == 422


def test_a_client_public_name_can_be_read_without_logging_in(harness: Harness) -> None:
    client_id = _register(harness)

    response = harness.client.get(f"/oauth/clients/{client_id}")

    assert response.json() == {"client_id": client_id, "client_name": "Claude Code"}


def test_an_unknown_client_public_name_answers_404(harness: Harness) -> None:
    response = harness.client.get("/oauth/clients/never-registered")

    assert (response.status_code, response.json()["error"]) == (404, "invalid_client")


# ---- authorize -------------------------------------------------------------------------------


def test_without_a_session_authorize_sends_the_user_through_github_login_and_back(harness: Harness) -> None:
    client_id = _register(harness)

    response = _authorize(harness, client_id)

    login = urlsplit(response.headers["location"])
    return_to = parse_qs(login.query)["return_to"][0]
    assert (response.status_code, login.path) == (302, "/api/oauth/github/login")
    assert return_to.startswith("/oauth/authorize?")
    assert _query(return_to) == {name: [value] for name, value in _authorize_params(client_id).items()}


def test_with_a_session_a_new_client_is_sent_to_the_consent_page(harness: Harness) -> None:
    client_id = _register(harness)
    _log_in(harness)

    response = _authorize(harness, client_id)

    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{FRONTEND_URL}/consent"
    assert _query(response.headers["location"])["client_id"] == [client_id]


def test_with_a_session_an_approved_client_gets_its_code_straight_away(harness: Harness) -> None:
    client_id = _register(harness)
    _log_in(harness)
    _decide(harness, client_id, approve=True)

    response = _authorize(harness, client_id)

    location = response.headers["location"]
    assert location.startswith(REDIRECT_URI)
    assert _query(location)["state"] == ["xyz"]
    assert len(_query(location)["code"][0]) >= 32


def test_an_approved_client_is_still_asked_again_by_a_different_user(harness: Harness) -> None:
    client_id = _register(harness)
    _log_in(harness)
    _decide(harness, client_id, approve=True)
    _log_in(harness, user_id=USER_ID + 1)

    response = _authorize(harness, client_id)

    assert response.headers["location"].startswith(f"{FRONTEND_URL}/consent")


def test_a_bearer_token_is_not_a_session_so_it_cannot_skip_the_login(harness: Harness) -> None:
    client_id = _register(harness)
    bearer = {"Authorization": f"Bearer {JWT_SERVICE.issue_access_token(user_id=USER_ID)}"}

    response = harness.client.get("/oauth/authorize", params=_authorize_params(client_id), headers=bearer)

    assert urlsplit(response.headers["location"]).path == "/api/oauth/github/login"


def test_a_loopback_client_may_come_back_on_a_different_port(harness: Harness) -> None:
    client_id = _register(harness)
    _log_in(harness)
    _decide(harness, client_id, approve=True)

    response = _authorize(harness, client_id, redirect_uri="http://localhost:60000/callback")

    assert response.headers["location"].startswith("http://localhost:60000/callback?code=")


@pytest.mark.parametrize(
    "overrides",
    [{"client_id": "never-registered"}, {"client_id": None}, {"redirect_uri": None}, {"redirect_uri": "https://evil.example.com/cb"}],
    ids=["unknown-client", "no-client", "no-redirect-uri", "unregistered-redirect-uri"],
)
def test_an_untrusted_client_or_redirect_uri_is_answered_directly_and_never_redirected(
    harness: Harness, overrides: dict
) -> None:
    client_id = _register(harness)
    _log_in(harness)

    response = _authorize(harness, **({"client_id": client_id} | overrides))

    assert response.status_code == 400
    assert "location" not in response.headers
    assert response.json()["error"] == "invalid_request"


@pytest.mark.parametrize(
    "overrides, error",
    [
        ({"response_type": "token"}, "unsupported_response_type"),
        ({"response_type": None}, "unsupported_response_type"),
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge_method": None}, "invalid_request"),
        ({"code_challenge": None}, "invalid_request"),
        ({"code_challenge": "too-short"}, "invalid_request"),
    ],
)
def test_a_malformed_request_from_a_trusted_client_is_redirected_back_with_the_error_and_state(
    harness: Harness, overrides: dict, error: str
) -> None:
    client_id = _register(harness)

    response = _authorize(harness, client_id, **overrides)

    location = response.headers["location"]
    assert location.startswith(REDIRECT_URI)
    assert _query(location)["error"] == [error]
    assert _query(location)["state"] == ["xyz"]


# ---- decision --------------------------------------------------------------------------------


def test_the_decision_needs_a_web_session(harness: Harness) -> None:
    client_id = _register(harness)

    assert _decide(harness, client_id, approve=True).status_code == 401


def test_an_access_token_cannot_approve_a_client(harness: Harness) -> None:
    client_id = _register(harness)
    bearer = {"Authorization": f"Bearer {JWT_SERVICE.issue_access_token(user_id=USER_ID)}"}

    response = harness.client.post(
        "/oauth/authorize/decision", json=_authorize_params(client_id) | {"approve": True}, headers=bearer
    )

    assert response.status_code == 401
    assert harness.session.consents == set()


def test_approving_returns_the_redirect_with_a_code_and_remembers_the_client(harness: Harness) -> None:
    client_id = _register(harness)
    _log_in(harness)

    response = _decide(harness, client_id, approve=True)

    redirect_to = response.json()["redirect_to"]
    assert redirect_to.startswith(REDIRECT_URI)
    assert _query(redirect_to)["state"] == ["xyz"]
    assert harness.session.consents == {(USER_ID, client_id)}


def test_denying_returns_access_denied_and_remembers_nothing(harness: Harness) -> None:
    client_id = _register(harness)
    _log_in(harness)

    response = _decide(harness, client_id, approve=False)

    redirect_to = response.json()["redirect_to"]
    assert _query(redirect_to)["error"] == ["access_denied"]
    assert _query(redirect_to)["state"] == ["xyz"]
    assert "code" not in _query(redirect_to)
    assert harness.session.consents == set()
    assert harness.redis.values == {}


def test_a_malformed_decision_returns_the_error_as_the_next_url_not_as_a_redirect(harness: Harness) -> None:
    client_id = _register(harness)
    _log_in(harness)

    response = _decide(harness, client_id, approve=True, code_challenge_method="plain")

    assert response.status_code == 200
    assert _query(response.json()["redirect_to"])["error"] == ["invalid_request"]
    assert harness.session.consents == set()


def test_a_decision_for_an_unregistered_redirect_uri_is_refused(harness: Harness) -> None:
    client_id = _register(harness)
    _log_in(harness)

    response = _decide(harness, client_id, approve=True, redirect_uri="https://evil.example.com/cb")

    assert response.status_code == 400
    assert harness.redis.values == {}


# ---- token -----------------------------------------------------------------------------------


def test_a_code_is_traded_for_tokens_that_are_never_cached(harness: Harness) -> None:
    client_id = _register(harness)
    code = _obtain_code(harness, client_id)

    response = _exchange(harness, client_id, code)

    body = response.json()
    assert response.status_code == 200
    assert (body["token_type"], body["expires_in"]) == ("Bearer", 3600)
    assert body["access_token"] and body["refresh_token"] and body["access_token"] != body["refresh_token"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_the_issued_tokens_belong_to_the_user_who_approved(harness: Harness) -> None:
    client_id = _register(harness)

    _obtain_tokens(harness, client_id)

    [row] = harness.repository.rows
    assert (row.user_id, row.client_id) == (USER_ID, client_id)


def test_a_code_works_only_once(harness: Harness) -> None:
    client_id = _register(harness)
    code = _obtain_code(harness, client_id)
    _exchange(harness, client_id, code)

    response = _exchange(harness, client_id, code)

    assert (response.status_code, response.json()["error"]) == (400, "invalid_grant")
    assert len(harness.repository.rows) == 1


@pytest.mark.parametrize(
    "overrides",
    [{"code_verifier": "x" * 43}, {"code_verifier": "short"}, {"redirect_uri": "http://localhost:1/other"}],
    ids=["wrong-verifier", "malformed-verifier", "different-redirect-uri"],
)
def test_a_code_presented_wrongly_is_invalid_grant_and_issues_nothing(harness: Harness, overrides: dict) -> None:
    client_id = _register(harness)
    code = _obtain_code(harness, client_id)

    response = _exchange(harness, client_id, code, **overrides)

    assert response.json()["error"] == "invalid_grant"
    assert harness.repository.rows == []


def test_a_code_cannot_be_redeemed_by_another_client(harness: Harness) -> None:
    owner = _register(harness)
    other = _register(harness)
    code = _obtain_code(harness, owner)

    response = _exchange(harness, other, code)

    assert response.json()["error"] == "invalid_grant"


def test_a_refresh_token_is_traded_for_a_new_pair(harness: Harness) -> None:
    client_id = _register(harness)
    first = _obtain_tokens(harness, client_id)

    response = _refresh(harness, client_id, first["refresh_token"])

    second = response.json()
    assert response.status_code == 200
    assert second["refresh_token"] != first["refresh_token"]
    assert second["access_token"] != first["access_token"]
    assert response.headers["cache-control"] == "no-store"


def test_reusing_an_old_refresh_token_is_invalid_grant_and_kills_the_new_one_too(harness: Harness) -> None:
    client_id = _register(harness)
    first = _obtain_tokens(harness, client_id)
    second = _refresh(harness, client_id, first["refresh_token"]).json()

    replay = _refresh(harness, client_id, first["refresh_token"])
    successor = _refresh(harness, client_id, second["refresh_token"])

    assert replay.json()["error"] == "invalid_grant"
    assert successor.json()["error"] == "invalid_grant"


def test_a_refresh_token_cannot_be_used_by_another_client(harness: Harness) -> None:
    owner, other = _register(harness), _register(harness)
    tokens = _obtain_tokens(harness, owner)

    assert _refresh(harness, other, tokens["refresh_token"]).json()["error"] == "invalid_grant"


def test_an_unknown_client_is_invalid_client(harness: Harness) -> None:
    response = harness.client.post(
        "/oauth/token", data={"grant_type": "refresh_token", "client_id": "never-registered", "refresh_token": "x"}
    )

    assert (response.status_code, response.json()["error"]) == (401, "invalid_client")


def test_an_unsupported_grant_type_is_refused(harness: Harness) -> None:
    client_id = _register(harness)

    response = harness.client.post("/oauth/token", data={"grant_type": "password", "client_id": client_id})

    assert (response.status_code, response.json()["error"]) == (400, "unsupported_grant_type")


@pytest.mark.parametrize(
    "form",
    [
        {},
        {"grant_type": "authorization_code"},
        {"grant_type": "authorization_code", "code": "c", "redirect_uri": REDIRECT_URI},
        {"grant_type": "authorization_code", "code": "c", "code_verifier": VERIFIER},
        {"grant_type": "authorization_code", "redirect_uri": REDIRECT_URI, "code_verifier": VERIFIER},
        {"grant_type": "refresh_token"},
    ],
    ids=["empty", "no-client", "no-verifier", "no-redirect-uri", "no-code", "no-refresh-token"],
)
def test_a_token_request_with_a_missing_field_is_invalid_request(harness: Harness, form: dict) -> None:
    client_id = _register(harness)
    form = form | ({"client_id": client_id} if form else {})

    response = harness.client.post("/oauth/token", data=form)

    assert (response.status_code, response.json()["error"]) == (400, "invalid_request")


def test_error_responses_expose_only_the_error_and_a_description(harness: Harness) -> None:
    client_id = _register(harness)
    code = _obtain_code(harness, client_id)

    body = _exchange(harness, client_id, code, code_verifier="x" * 43).json()

    assert set(body) == {"error", "error_description"}


# ---- revoke ----------------------------------------------------------------------------------


def test_revoking_the_refresh_token_ends_the_authorization(harness: Harness) -> None:
    client_id = _register(harness)
    tokens = _obtain_tokens(harness, client_id)

    response = harness.client.post("/oauth/revoke", data={"token": tokens["refresh_token"]})

    assert (response.status_code, response.json()) == (200, {})
    assert _refresh(harness, client_id, tokens["refresh_token"]).json()["error"] == "invalid_grant"


def test_revoking_the_access_token_ends_the_authorization_too(harness: Harness) -> None:
    client_id = _register(harness)
    tokens = _obtain_tokens(harness, client_id)

    harness.client.post("/oauth/revoke", data={"token": tokens["access_token"]})

    assert _refresh(harness, client_id, tokens["refresh_token"]).json()["error"] == "invalid_grant"


def test_revoking_an_unknown_token_still_answers_200(harness: Harness) -> None:
    response = harness.client.post("/oauth/revoke", data={"token": "never-issued"})

    assert response.status_code == 200


def test_revoking_without_a_token_is_invalid_request(harness: Harness) -> None:
    response = harness.client.post("/oauth/revoke", data={})

    assert (response.status_code, response.json()["error"]) == (400, "invalid_request")
