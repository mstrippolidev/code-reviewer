import base64
import hashlib
import hmac
import re

from api.oauth.errors import InvalidGrantError

VERIFIER_PATTERN = re.compile(r"[A-Za-z0-9\-._~]{43,128}")


def verify_pkce_s256(code_verifier: str, code_challenge: str) -> None:
    """Raises InvalidGrantError unless the verifier is well formed and hashes to the challenge."""
    if not VERIFIER_PATTERN.fullmatch(code_verifier):
        raise InvalidGrantError("PKCE verifier is malformed")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=")
    if not hmac.compare_digest(expected, code_challenge.encode("utf-8")):
        raise InvalidGrantError("PKCE verifier does not match the challenge")
