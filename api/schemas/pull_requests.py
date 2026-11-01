import re
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator

from api.schemas.reviews import AgentSelection

GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
PULL_REQUEST_PATH = re.compile(r"^/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<number>[0-9]+)(?:/.*)?$")
PULL_REQUEST_URL_HELP = "Use a GitHub pull request URL such as https://github.com/owner/repo/pull/123"


class PullRequestRef(BaseModel):
    """Which pull request a URL points at: the repo's GitHub full name and the pull request number."""

    full_name: str
    number: int


def parse_pull_request_url(pr_url: str) -> PullRequestRef:
    """Reads the repo and number out of a github.com pull request URL; anything after the number is ignored.

    Raises:
        ValueError: If the URL is not a github.com pull request URL.
    """
    parsed = urlparse(pr_url.strip())
    if parsed.scheme not in ("http", "https") or parsed.hostname not in GITHUB_HOSTS:
        raise ValueError(f"Only github.com pull request URLs are supported. {PULL_REQUEST_URL_HELP}")
    match = PULL_REQUEST_PATH.match(parsed.path)
    if match is None or int(match["number"]) == 0:
        raise ValueError(f"Not a pull request URL. {PULL_REQUEST_URL_HELP}")
    return PullRequestRef(full_name=f"{match['owner']}/{match['repo']}", number=int(match["number"]))


class PullRequestReviewRequest(BaseModel):
    """A pull request the user wants reviewed, named by its URL, optionally by a subset of agents."""

    pr_url: str
    agents: AgentSelection | None = None

    @field_validator("pr_url")
    @classmethod
    def _is_a_pull_request_url(cls, pr_url: str) -> str:
        """Rejects a URL that does not name a github.com pull request, so the route never sees one."""
        parse_pull_request_url(pr_url)
        return pr_url

    @property
    def pull_request(self) -> PullRequestRef:
        """The repo and number the URL names."""
        return parse_pull_request_url(self.pr_url)
