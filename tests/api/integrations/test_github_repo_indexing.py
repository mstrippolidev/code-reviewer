"""
    Tests for GitHubOAuthClient's repo-indexing methods (commit resolution, tarball
    download) against faked HTTP responses (respx), no real network calls.
"""
import httpx
import pytest
import respx

from api.integrations.github import (
    REPO_INDEXING_REQUEST_TIMEOUT_SECONDS,
    GitHubCommitFetchError,
    GitHubOAuthClient,
    GitHubOAuthConfig,
    GitHubTarballFetchError,
)

CONFIG = GitHubOAuthConfig(
    client_id="test-client-id",
    client_secret="test-client-secret",
    redirect_uri="http://localhost:8000/api/oauth/github/callback",
)


def _client() -> GitHubOAuthClient:
    return GitHubOAuthClient(CONFIG, httpx.AsyncClient())


@pytest.mark.asyncio
@respx.mock
async def test_fetch_branch_commit_sha_returns_the_sha() -> None:
    respx.get("https://api.github.com/repos/octocat/hello-world/commits/main").mock(
        return_value=httpx.Response(200, json={"sha": "abc123def"})
    )

    sha = await _client().fetch_branch_commit_sha("gho_token", "octocat/hello-world", "main")

    assert sha == "abc123def"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_branch_commit_sha_raises_on_an_http_status_error() -> None:
    respx.get("https://api.github.com/repos/octocat/hello-world/commits/main").mock(
        return_value=httpx.Response(404, text="Not Found")
    )

    with pytest.raises(GitHubCommitFetchError):
        await _client().fetch_branch_commit_sha("gho_token", "octocat/hello-world", "main")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_branch_commit_sha_raises_on_a_network_error() -> None:
    respx.get("https://api.github.com/repos/octocat/hello-world/commits/main").mock(
        side_effect=httpx.ConnectError("down")
    )

    with pytest.raises(GitHubCommitFetchError):
        await _client().fetch_branch_commit_sha("gho_token", "octocat/hello-world", "main")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_branch_commit_sha_raises_when_github_is_unresponsive() -> None:
    respx.get("https://api.github.com/repos/octocat/hello-world/commits/main").mock(
        side_effect=httpx.ReadTimeout("no response")
    )

    with pytest.raises(GitHubCommitFetchError):
        await _client().fetch_branch_commit_sha("gho_token", "octocat/hello-world", "main")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_branch_commit_sha_enforces_the_configured_timeout() -> None:
    route = respx.get("https://api.github.com/repos/octocat/hello-world/commits/main").mock(
        return_value=httpx.Response(200, json={"sha": "abc123def"})
    )

    await _client().fetch_branch_commit_sha("gho_token", "octocat/hello-world", "main")

    applied_timeout = route.calls.last.request.extensions["timeout"]
    assert applied_timeout["connect"] == REPO_INDEXING_REQUEST_TIMEOUT_SECONDS
    assert applied_timeout["read"] == REPO_INDEXING_REQUEST_TIMEOUT_SECONDS


@pytest.mark.asyncio
@respx.mock
async def test_download_tarball_returns_the_raw_bytes() -> None:
    respx.get("https://api.github.com/repos/octocat/hello-world/tarball/abc123").mock(
        return_value=httpx.Response(200, content=b"fake-tarball-bytes")
    )

    tarball = await _client().download_tarball("gho_token", "octocat/hello-world", "abc123")

    assert tarball == b"fake-tarball-bytes"


@pytest.mark.asyncio
@respx.mock
async def test_download_tarball_follows_githubs_redirect_to_codeload() -> None:
    respx.get("https://api.github.com/repos/octocat/hello-world/tarball/abc123").mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://codeload.github.com/octocat/hello-world/tar.gz/abc123"}
        )
    )
    respx.get("https://codeload.github.com/octocat/hello-world/tar.gz/abc123").mock(
        return_value=httpx.Response(200, content=b"fake-tarball-bytes")
    )

    tarball = await _client().download_tarball("gho_token", "octocat/hello-world", "abc123")

    assert tarball == b"fake-tarball-bytes"


@pytest.mark.asyncio
@respx.mock
async def test_download_tarball_raises_on_an_http_status_error() -> None:
    respx.get("https://api.github.com/repos/octocat/hello-world/tarball/abc123").mock(
        return_value=httpx.Response(404, text="Not Found")
    )

    with pytest.raises(GitHubTarballFetchError):
        await _client().download_tarball("gho_token", "octocat/hello-world", "abc123")


@pytest.mark.asyncio
@respx.mock
async def test_download_tarball_raises_when_github_is_unresponsive() -> None:
    respx.get("https://api.github.com/repos/octocat/hello-world/tarball/abc123").mock(
        side_effect=httpx.ReadTimeout("no response")
    )

    with pytest.raises(GitHubTarballFetchError):
        await _client().download_tarball("gho_token", "octocat/hello-world", "abc123")


@pytest.mark.asyncio
@respx.mock
async def test_download_tarball_enforces_the_configured_timeout() -> None:
    route = respx.get("https://api.github.com/repos/octocat/hello-world/tarball/abc123").mock(
        return_value=httpx.Response(200, content=b"fake-tarball-bytes")
    )

    await _client().download_tarball("gho_token", "octocat/hello-world", "abc123")

    applied_timeout = route.calls.last.request.extensions["timeout"]
    assert applied_timeout["read"] == REPO_INDEXING_REQUEST_TIMEOUT_SECONDS
