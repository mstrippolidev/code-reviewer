"""
    Tests for the return_to safety check and the redirect URL helpers: pure logic, no I/O.
"""
from urllib.parse import parse_qs, urlsplit

import pytest

from api.oauth.errors import AuthorizationRedirectError, InvalidReturnToError
from api.oauth.redirects import append_query, authorization_error_url
from api.oauth.return_to import require_safe_return_to


def test_an_authorize_path_is_accepted_unchanged() -> None:
    path = "/oauth/authorize?client_id=abc&redirect_uri=http%3A%2F%2Flocalhost%3A1%2Fcb"

    assert require_safe_return_to(path) == path


@pytest.mark.parametrize(
    "return_to",
    [
        "",
        "https://evil.example.com/oauth/authorize?x=1",
        "//evil.example.com/oauth/authorize?x=1",
        "/\\evil.example.com",
        "/oauth/authorize",
        "/oauth/authorize/../../admin?x=1",
        "/oauth/token?x=1",
        "/api/repos",
        "/oauth/authorize?x=1\nSet-Cookie: a=b",
        "/oauth/authorize?x=1 y",
        "/oauth/authorize?" + "a" * 5000,
    ],
)
def test_anything_but_a_local_authorize_request_is_rejected(return_to: str) -> None:
    with pytest.raises(InvalidReturnToError):
        require_safe_return_to(return_to)


def test_append_query_adds_parameters() -> None:
    url = append_query("http://localhost:1/cb", {"code": "abc", "state": "xyz"})

    assert parse_qs(urlsplit(url).query) == {"code": ["abc"], "state": ["xyz"]}


def test_append_query_keeps_the_existing_query() -> None:
    url = append_query("http://localhost:1/cb?keep=1", {"code": "abc"})

    assert parse_qs(urlsplit(url).query) == {"keep": ["1"], "code": ["abc"]}


def test_append_query_escapes_values() -> None:
    url = append_query("http://localhost:1/cb", {"state": "a&b=c d"})

    assert parse_qs(urlsplit(url).query) == {"state": ["a&b=c d"]}


def test_append_query_works_on_a_custom_scheme() -> None:
    assert append_query("cursor://app/cb", {"code": "abc"}) == "cursor://app/cb?code=abc"


def test_an_authorization_error_url_carries_the_error_and_the_state() -> None:
    error = AuthorizationRedirectError("http://localhost:1/cb", "access_denied", "no thanks", "xyz")

    query = parse_qs(urlsplit(authorization_error_url(error)).query)

    assert query == {"error": ["access_denied"], "error_description": ["no thanks"], "state": ["xyz"]}


def test_an_authorization_error_url_omits_a_missing_state() -> None:
    error = AuthorizationRedirectError("http://localhost:1/cb", "access_denied", "no thanks", None)

    assert "state" not in parse_qs(urlsplit(authorization_error_url(error)).query)
