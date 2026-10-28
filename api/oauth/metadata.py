from pydantic import BaseModel


class AuthorizationServerMetadata(BaseModel):
    """The RFC 8414 document a client reads to find every other OAuth endpoint."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str
    revocation_endpoint: str
    response_types_supported: list[str]
    grant_types_supported: list[str]
    code_challenge_methods_supported: list[str]
    token_endpoint_auth_methods_supported: list[str]
    revocation_endpoint_auth_methods_supported: list[str]


def build_authorization_server_metadata(issuer: str) -> AuthorizationServerMetadata:
    return AuthorizationServerMetadata(
        issuer=issuer,
        authorization_endpoint=f"{issuer}/oauth/authorize",
        token_endpoint=f"{issuer}/oauth/token",
        registration_endpoint=f"{issuer}/oauth/register",
        revocation_endpoint=f"{issuer}/oauth/revoke",
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        code_challenge_methods_supported=["S256"],
        token_endpoint_auth_methods_supported=["none"],
        revocation_endpoint_auth_methods_supported=["none"],
    )
