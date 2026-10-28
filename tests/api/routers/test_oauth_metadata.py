"""
    Tests for GET /.well-known/oauth-authorization-server: a static document, no I/O.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.oauth.dependencies import get_oauth_issuer
from api.routers.oauth import router as oauth_router

ISSUER = "https://api.example.test"


@pytest.fixture
def metadata() -> dict:
    app = FastAPI()
    app.include_router(oauth_router)
    app.dependency_overrides[get_oauth_issuer] = lambda: ISSUER
    return TestClient(app).get("/.well-known/oauth-authorization-server").json()


def test_the_issuer_is_the_configured_public_address(metadata: dict) -> None:
    assert metadata["issuer"] == ISSUER


@pytest.mark.parametrize(
    "field, path",
    [
        ("authorization_endpoint", "/oauth/authorize"),
        ("token_endpoint", "/oauth/token"),
        ("registration_endpoint", "/oauth/register"),
        ("revocation_endpoint", "/oauth/revoke"),
    ],
)
def test_every_endpoint_url_is_built_from_the_issuer(metadata: dict, field: str, path: str) -> None:
    assert metadata[field] == f"{ISSUER}{path}"


def test_only_s256_pkce_is_offered(metadata: dict) -> None:
    assert metadata["code_challenge_methods_supported"] == ["S256"]


def test_only_the_code_flow_and_refresh_are_offered(metadata: dict) -> None:
    assert metadata["response_types_supported"] == ["code"]
    assert sorted(metadata["grant_types_supported"]) == ["authorization_code", "refresh_token"]


def test_clients_authenticate_with_nothing_because_they_are_public(metadata: dict) -> None:
    assert metadata["token_endpoint_auth_methods_supported"] == ["none"]
    assert metadata["revocation_endpoint_auth_methods_supported"] == ["none"]
