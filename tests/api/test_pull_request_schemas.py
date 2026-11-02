"""
    Tests for the pull request URL parsing and the review request model.
"""
import pytest
from pydantic import ValidationError

from api.schemas.pull_requests import PullRequestRef, PullRequestReviewRequest, parse_pull_request_url
from code_reviewer.schemas.review import CodeKey

VALID_URLS = [
    ("https://github.com/acme/api/pull/123", PullRequestRef(full_name="acme/api", number=123)),
    ("http://github.com/acme/api/pull/123", PullRequestRef(full_name="acme/api", number=123)),
    ("https://www.github.com/acme/api/pull/123", PullRequestRef(full_name="acme/api", number=123)),
    ("https://github.com/acme/api/pull/123/", PullRequestRef(full_name="acme/api", number=123)),
    ("https://github.com/acme/api/pull/123/files", PullRequestRef(full_name="acme/api", number=123)),
    ("https://github.com/acme/api/pull/123/commits/abc#diff-1", PullRequestRef(full_name="acme/api", number=123)),
    ("https://github.com/acme/api/pull/123?diff=split", PullRequestRef(full_name="acme/api", number=123)),
    ("  https://github.com/acme/api/pull/123  ", PullRequestRef(full_name="acme/api", number=123)),
    ("https://github.com/my-org/my.repo_name/pull/9", PullRequestRef(full_name="my-org/my.repo_name", number=9)),
]
INVALID_URLS = [
    "",
    "not a url",
    "https://gitlab.com/acme/api/pull/123",
    "https://github.example.com/acme/api/pull/123",
    "https://evilgithub.com/acme/api/pull/123",
    "https://github.com.evil.com/acme/api/pull/123",
    "ftp://github.com/acme/api/pull/123",
    "https://github.com/acme/api",
    "https://github.com/acme/api/pulls",
    "https://github.com/acme/api/pulls/123",
    "https://github.com/acme/api/issues/123",
    "https://github.com/acme/api/pull/abc",
    "https://github.com/acme/api/pull/0",
    "https://github.com/acme/pull/123",
    "123",
]


@pytest.mark.parametrize("pr_url,expected", VALID_URLS)
def test_parse_pull_request_url_reads_the_repo_and_number(pr_url: str, expected: PullRequestRef) -> None:
    """Verify every common way of copying a pull request link names the same repo and number."""
    assert parse_pull_request_url(pr_url) == expected


@pytest.mark.parametrize("pr_url", INVALID_URLS)
def test_parse_pull_request_url_rejects_anything_that_is_not_a_github_pull_request(pr_url: str) -> None:
    """Verify other hosts, look-alike hosts and other GitHub pages are refused instead of guessed at."""
    with pytest.raises(ValueError):
        parse_pull_request_url(pr_url)


def test_parse_pull_request_url_error_shows_the_expected_form() -> None:
    """Verify the refusal tells the caller what a valid URL looks like."""
    with pytest.raises(ValueError, match="https://github.com/owner/repo/pull/123"):
        parse_pull_request_url("https://github.com/acme/api")


def test_review_request_exposes_the_pull_request_its_url_names() -> None:
    """Verify callers read the repo and number from the request instead of parsing again."""
    request = PullRequestReviewRequest(pr_url="https://github.com/acme/api/pull/5")

    assert request.pull_request == PullRequestRef(full_name="acme/api", number=5)


def test_review_request_without_agents_runs_every_agent() -> None:
    """Verify an omitted selection means no restriction."""
    request = PullRequestReviewRequest(pr_url="https://github.com/acme/api/pull/5")

    assert request.agents is None


def test_review_request_accepts_a_subset_of_agents() -> None:
    """Verify a pull request can be reviewed by only the agents the user asked about."""
    request = PullRequestReviewRequest(pr_url="https://github.com/acme/api/pull/5", agents=["TEST", "DRY"])

    assert request.agents == [CodeKey.TEST, CodeKey.DRY]


def test_review_request_with_an_invalid_url_is_rejected_at_validation() -> None:
    """Verify a bad URL is a validation error, which the route answers as a 422."""
    with pytest.raises(ValidationError):
        PullRequestReviewRequest(pr_url="https://gitlab.com/acme/api/pull/5")


def test_review_request_with_an_unknown_agent_is_rejected() -> None:
    """Verify the same agent validation as the other review requests applies."""
    with pytest.raises(ValidationError):
        PullRequestReviewRequest(pr_url="https://github.com/acme/api/pull/5", agents=["NOPE"])
