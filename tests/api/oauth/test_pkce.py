"""
    Tests for the PKCE S256 check: pure logic, no I/O.
"""
import pytest

from api.oauth.errors import InvalidGrantError
from api.oauth.pkce import verify_pkce_s256

RFC_7636_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC_7636_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_the_rfc_7636_example_verifies() -> None:
    assert verify_pkce_s256(RFC_7636_VERIFIER, RFC_7636_CHALLENGE) is None


def test_a_different_verifier_is_rejected() -> None:
    other_verifier = "x" * 43

    with pytest.raises(InvalidGrantError):
        verify_pkce_s256(other_verifier, RFC_7636_CHALLENGE)


def test_the_challenge_itself_is_not_accepted_as_the_verifier() -> None:
    with pytest.raises(InvalidGrantError):
        verify_pkce_s256(RFC_7636_CHALLENGE, RFC_7636_CHALLENGE)


@pytest.mark.parametrize(
    "verifier",
    ["", "short", "x" * 42, "x" * 129, "x" * 42 + " ", "x" * 42 + "é", "x" * 42 + "="],
    ids=["empty", "short", "one-below-minimum", "one-above-maximum", "space", "non-ascii", "padding"],
)
def test_a_malformed_verifier_is_rejected(verifier: str) -> None:
    with pytest.raises(InvalidGrantError):
        verify_pkce_s256(verifier, RFC_7636_CHALLENGE)


@pytest.mark.parametrize("length", [43, 128])
def test_the_length_limits_are_inclusive(length: int) -> None:
    with pytest.raises(InvalidGrantError, match="does not match"):
        verify_pkce_s256("x" * length, RFC_7636_CHALLENGE)


@pytest.mark.parametrize("challenge", ["", RFC_7636_CHALLENGE + "=", RFC_7636_CHALLENGE.lower(), "é"])
def test_a_wrong_or_malformed_challenge_is_rejected(challenge: str) -> None:
    with pytest.raises(InvalidGrantError):
        verify_pkce_s256(RFC_7636_VERIFIER, challenge)
