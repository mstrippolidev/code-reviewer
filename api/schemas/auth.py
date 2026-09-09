from pydantic import BaseModel, ConfigDict


class AuthTokenResponse(BaseModel):
    """Response returned after a successful GitHub OAuth login."""

    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    """Public-facing representation of an authenticated user; never includes the stored GitHub token."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    github_id: int
    github_username: str
    email: str | None = None
    avatar_url: str | None = None
    github_granted_scopes: str
