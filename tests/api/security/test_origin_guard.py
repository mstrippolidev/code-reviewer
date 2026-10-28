"""
    Tests for CookieOriginGuard: pure middleware behavior against a trivial app, no I/O.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import GUEST_SESSION_COOKIE, USER_SESSION_COOKIE
from api.security.origin_guard import CookieOriginGuard

ALLOWED_ORIGIN = "http://localhost:5173"
EVIL_ORIGIN = "https://evil.example"


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.post("/write")
    async def write() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/read")
    async def read() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(CookieOriginGuard, allowed_origins=frozenset({ALLOWED_ORIGIN}))
    return TestClient(app)


def test_a_cookie_write_from_the_allowed_origin_passes(client: TestClient) -> None:
    response = client.post("/write", cookies={USER_SESSION_COOKIE: "t"}, headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200


def test_a_cookie_write_from_another_origin_is_rejected(client: TestClient) -> None:
    response = client.post("/write", cookies={USER_SESSION_COOKIE: "t"}, headers={"Origin": EVIL_ORIGIN})

    assert response.status_code == 403


def test_a_cookie_write_without_an_origin_header_is_rejected(client: TestClient) -> None:
    assert client.post("/write", cookies={USER_SESSION_COOKIE: "t"}).status_code == 403


def test_the_guest_cookie_is_guarded_too(client: TestClient) -> None:
    response = client.post("/write", cookies={GUEST_SESSION_COOKIE: "t"}, headers={"Origin": EVIL_ORIGIN})

    assert response.status_code == 403


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_every_state_changing_method_is_guarded(method: str) -> None:
    app = FastAPI()
    app.add_api_route("/write", lambda: {"ok": True}, methods=[method.upper()])
    app.add_middleware(CookieOriginGuard, allowed_origins=frozenset({ALLOWED_ORIGIN}))

    response = TestClient(app).request(method, "/write", cookies={USER_SESSION_COOKIE: "t"})

    assert response.status_code == 403


def test_a_bearer_request_needs_no_origin(client: TestClient) -> None:
    response = client.post("/write", headers={"Authorization": "Bearer t"})

    assert response.status_code == 200


def test_a_request_with_no_session_cookie_is_not_guarded(client: TestClient) -> None:
    assert client.post("/write", headers={"Origin": EVIL_ORIGIN}).status_code == 200


def test_reads_are_never_guarded(client: TestClient) -> None:
    response = client.get("/read", cookies={USER_SESSION_COOKIE: "t"}, headers={"Origin": EVIL_ORIGIN})

    assert response.status_code == 200
