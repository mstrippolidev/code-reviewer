from pydantic import BaseModel


class GitHubUserProfile(BaseModel):
    """The subset of a GitHub user's profile this app needs after OAuth login."""

    github_id: int
    github_username: str
    email: str | None = None
    avatar_url: str | None = None


class GitHubRepo(BaseModel):
    """A repo listed for the logged-in user; repo_id/owner_id match the RAG scoping keys."""

    repo_id: int
    owner_id: int
    full_name: str
    description: str | None = None
    private: bool
    default_branch: str
    language: str | None = None
    python_percentage: float
    has_enough_python: bool
