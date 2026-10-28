from api.oauth.errors import InvalidReturnToError

AUTHORIZE_PATH_PREFIX = "/oauth/authorize?"
MAX_RETURN_TO_LENGTH = 4096


def require_safe_return_to(return_to: str) -> str:
    """Returns the path unchanged if it is an authorize request on this server; anything else could redirect off-site."""
    is_authorize_path = return_to.startswith(AUTHORIZE_PATH_PREFIX)
    has_unsafe_character = any(character.isspace() or ord(character) < 32 or character == "\\" for character in return_to)
    if not is_authorize_path or has_unsafe_character or len(return_to) > MAX_RETURN_TO_LENGTH:
        raise InvalidReturnToError("return_to must be an /oauth/authorize request on this server")
    return return_to
