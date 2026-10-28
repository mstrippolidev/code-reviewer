"""
    Tests for redirect URI validation and matching: pure logic, no I/O.
"""
import pytest

from api.oauth.errors import InvalidRedirectUriError
from api.oauth.redirect_uri import redirect_uri_matches, validate_redirect_uri


@pytest.mark.parametrize(
    "uri",
    [
        "https://app.example.com/callback",
        "https://app.example.com:8443/cb?x=1",
        "http://localhost:53682/callback",
        "http://127.0.0.1:9999/cb",
        "http://[::1]:9999/cb",
        "http://localhost/cb",
        "cursor://anysphere.cursor-retrieval/oauth/callback",
        "com.example.app:/oauth2redirect",
    ],
)
def test_an_acceptable_redirect_uri_is_accepted(uri: str) -> None:
    assert validate_redirect_uri(uri) is None


@pytest.mark.parametrize(
    "uri",
    [
        "",
        "   ",
        "/relative/path",
        "app.example.com/callback",
        "http://app.example.com/callback",
        "http://192.168.1.5/callback",
        "http://localhost.evil.com/cb",
        "https://app.example.com/cb#fragment",
        "https://app.example.com/cb#",
        "https://user:pass@app.example.com/cb",
        "https:///nohost",
        "javascript:alert(1)",
        "data:text/html,hello",
        "file:///etc/passwd",
        "ftp://app.example.com/cb",
        "cursor:",
        "https://app.example.com/a b",
        "https://app.example.com/a\nb",
        "http://[::1/cb",
    ],
)
def test_an_unacceptable_redirect_uri_is_rejected(uri: str) -> None:
    with pytest.raises(InvalidRedirectUriError):
        validate_redirect_uri(uri)


def test_a_registered_uri_matches_itself() -> None:
    assert redirect_uri_matches(["https://app.example.com/cb"], "https://app.example.com/cb")


def test_an_unregistered_uri_does_not_match() -> None:
    assert not redirect_uri_matches(["https://app.example.com/cb"], "https://evil.example.com/cb")


@pytest.mark.parametrize("requested", ["https://app.example.com/cb/", "https://app.example.com/cb?x=1", "HTTPS://app.example.com/other"])
def test_a_non_loopback_uri_must_match_exactly(requested: str) -> None:
    assert not redirect_uri_matches(["https://app.example.com/cb"], requested)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_a_loopback_uri_may_use_a_different_port(host: str) -> None:
    assert redirect_uri_matches([f"http://{host}:1111/callback"], f"http://{host}:2222/callback")


def test_a_loopback_uri_with_a_different_path_does_not_match() -> None:
    assert not redirect_uri_matches(["http://localhost:1111/callback"], "http://localhost:1111/other")


def test_a_loopback_uri_with_a_different_host_does_not_match() -> None:
    assert not redirect_uri_matches(["http://localhost:1111/cb"], "http://127.0.0.1:1111/cb")


def test_the_port_flexibility_does_not_extend_to_https() -> None:
    assert not redirect_uri_matches(["https://localhost:1111/cb"], "https://localhost:2222/cb")


def test_a_custom_scheme_must_match_exactly() -> None:
    assert not redirect_uri_matches(["cursor://app/callback"], "cursor://other/callback")


def test_a_malformed_requested_uri_is_rejected() -> None:
    with pytest.raises(InvalidRedirectUriError):
        redirect_uri_matches(["https://app.example.com/cb"], "http://[::1/cb")
