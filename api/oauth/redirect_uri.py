import re
from urllib.parse import SplitResult, urlsplit

from api.oauth.errors import InvalidRedirectUriError

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
FORBIDDEN_SCHEMES = frozenset({"javascript", "data", "file", "vbscript", "about", "blob", "ftp", "ws", "wss"})
SCHEME_PATTERN = re.compile(r"[a-z][a-z0-9+.\-]*")


def validate_redirect_uri(uri: str) -> None:
    """Accepts https, http on loopback only, and private-use schemes such as `cursor://`."""
    if not uri or any(character.isspace() or ord(character) < 32 for character in uri):
        raise InvalidRedirectUriError("redirect URI must not be empty or contain whitespace")
    if "#" in uri:
        raise InvalidRedirectUriError("redirect URI must not contain a fragment")
    parts = _split(uri)
    if not SCHEME_PATTERN.fullmatch(parts.scheme):
        raise InvalidRedirectUriError("redirect URI must be absolute")
    if "@" in parts.netloc:
        raise InvalidRedirectUriError("redirect URI must not contain credentials")
    if parts.scheme == "https":
        _require_host(parts.hostname)
    elif parts.scheme == "http":
        _require_loopback(parts.hostname)
    elif parts.scheme in FORBIDDEN_SCHEMES or not (parts.netloc or parts.path):
        raise InvalidRedirectUriError(f"redirect URI scheme '{parts.scheme}' is not allowed")


def redirect_uri_matches(registered_uris: list[str], requested_uri: str) -> bool:
    """Exact match, except a loopback http URI may differ in port (RFC 8252, section 7.3)."""
    if requested_uri in registered_uris:
        return True
    requested = _split(requested_uri)
    if requested.scheme != "http" or requested.hostname not in LOOPBACK_HOSTS:
        return False
    return any(_same_loopback_target(_split(registered), requested) for registered in registered_uris)


def _same_loopback_target(registered: SplitResult, requested: SplitResult) -> bool:
    return (
        registered.scheme == "http"
        and registered.hostname == requested.hostname
        and registered.path == requested.path
        and registered.query == requested.query
    )


def _split(uri: str) -> SplitResult:
    try:
        return urlsplit(uri)
    except ValueError as error:
        raise InvalidRedirectUriError("redirect URI is malformed") from error


def _require_host(hostname: str | None) -> None:
    if not hostname:
        raise InvalidRedirectUriError("redirect URI must have a host")


def _require_loopback(hostname: str | None) -> None:
    if hostname not in LOOPBACK_HOSTS:
        raise InvalidRedirectUriError("http redirect URIs are only allowed on localhost, 127.0.0.1 or [::1]")
