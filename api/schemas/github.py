from pydantic import BaseModel


class GitHubUserProfile(BaseModel):
    """The subset of a GitHub user's profile this app needs after OAuth login."""

    github_id: int
    github_username: str
    email: str | None = None
    avatar_url: str | None = None
