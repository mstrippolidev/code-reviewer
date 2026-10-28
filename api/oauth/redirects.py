from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from api.oauth.errors import AuthorizationRedirectError


def append_query(url: str, params: dict[str, str]) -> str:
    """Adds query parameters to a URL, keeping the ones it already has."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True) + list(params.items())
    return urlunsplit(parts._replace(query=urlencode(query)))


def authorization_error_url(error: AuthorizationRedirectError) -> str:
    params = {"error": error.error, "error_description": error.description}
    if error.state is not None:
        params["state"] = error.state
    return append_query(error.redirect_uri, params)
