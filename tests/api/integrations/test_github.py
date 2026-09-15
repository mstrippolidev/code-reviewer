"""
    Tests for GitHubOAuthClient against faked HTTP responses (respx), no real network calls.
"""
import httpx
import pytest
import respx

from api.integrations.github import (
    GitHubOAuthClient,
    GitHubOAuthConfig,
    GitHubOAuthLoginError,
    GitHubProfileFetchError,
    GitHubRepoAccessLevel,
    GitHubRepoFetchError,
)

CONFIG = GitHubOAuthConfig(
    client_id="test-client-id",
    client_secret="test-client-secret",
    redirect_uri="http://localhost:8000/api/oauth/github/callback",
)


def _client() -> GitHubOAuthClient:
    return GitHubOAuthClient(CONFIG, httpx.AsyncClient())


def test_build_authorize_url_requests_full_repo_access_for_all() -> None:
    url = _client().build_authorize_url(state="state123", access_level=GitHubRepoAccessLevel.ALL)

    assert "scope=repo+read%3Auser" in url
    assert "client_id=test-client-id" in url
    assert "state=state123" in url


def test_build_authorize_url_restricts_scope_to_public_repos() -> None:
    url = _client().build_authorize_url(state="state123", access_level=GitHubRepoAccessLevel.PUBLIC)

    assert "scope=public_repo+read%3Auser" in url


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_token_returns_the_granted_scopes() -> None:
    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "gho_token", "scope": "repo,read:user"})
    )

    grant = await _client().exchange_code_for_token("some-code")

    assert grant.access_token == "gho_token"
    assert grant.granted_scopes == "repo,read:user"


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_token_raises_when_github_returns_no_token() -> None:
    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"error_description": "bad_verification_code"})
    )

    with pytest.raises(GitHubOAuthLoginError):
        await _client().exchange_code_for_token("some-code")


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_token_raises_on_a_network_error() -> None:
    respx.post("https://github.com/login/oauth/access_token").mock(side_effect=httpx.ConnectError("down"))

    with pytest.raises(GitHubOAuthLoginError):
        await _client().exchange_code_for_token("some-code")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_user_profile_parses_the_response() -> None:
    respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(
            200,
            json={"id": 1, "login": "octocat", "email": "octocat@example.com", "avatar_url": "http://img"},
        )
    )

    profile = await _client().fetch_user_profile("gho_token")

    assert profile.github_id == 1
    assert profile.github_username == "octocat"
    assert profile.email == "octocat@example.com"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_user_profile_raises_on_an_http_error() -> None:
    respx.get("https://api.github.com/user").mock(return_value=httpx.Response(401, text="Bad credentials"))

    with pytest.raises(GitHubProfileFetchError):
        await _client().fetch_user_profile("bad-token")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_repo_parses_the_response_and_python_percentage() -> None:
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 10,
                "owner": {"id": 99},
                "full_name": "octocat/hello-world",
                "description": None,
                "private": False,
                "default_branch": "main",
                "language": "Python",
            },
        )
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/languages").mock(
        return_value=httpx.Response(200, json={"Python": 20, "HTML": 80})
    )

    repo = await _client().fetch_repo("gho_token", "octocat/hello-world")

    assert repo.repo_id == 10
    assert repo.python_percentage == 20.0
    assert repo.has_enough_python is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_repo_raises_on_an_http_error() -> None:
    respx.get("https://api.github.com/repos/octocat/does-not-exist").mock(
        return_value=httpx.Response(404, text="Not Found")
    )

    with pytest.raises(GitHubRepoFetchError):
        await _client().fetch_repo("gho_token", "octocat/does-not-exist")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_repo_languages_raises_on_an_http_error() -> None:
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 10,
                "owner": {"id": 99},
                "full_name": "octocat/hello-world",
                "description": None,
                "private": False,
                "default_branch": "main",
                "language": "Python",
            },
        )
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/languages").mock(
        return_value=httpx.Response(403, text="rate limited")
    )

    with pytest.raises(GitHubRepoFetchError):
        await _client().fetch_repo("gho_token", "octocat/hello-world")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_user_repos_parses_repo_id_and_owner_id() -> None:
    respx.get("https://api.github.com/user/repos").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 10,
                    "owner": {"id": 99},
                    "full_name": "octocat/hello-world",
                    "description": "a repo",
                    "private": False,
                    "default_branch": "main",
                    "language": "Python",
                }
            ],
        )
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/languages").mock(
        return_value=httpx.Response(200, json={"Python": 80, "HTML": 20})
    )

    repos = await _client().fetch_user_repos("gho_token", page=1)

    assert len(repos) == 1
    assert repos[0].repo_id == 10
    assert repos[0].owner_id == 99
    assert repos[0].full_name == "octocat/hello-world"
    assert repos[0].default_branch == "main"
    assert repos[0].python_percentage == 80.0
    assert repos[0].has_enough_python is True


@pytest.mark.asyncio
@respx.mock
async def test_fetch_user_repos_flags_repos_below_the_python_threshold() -> None:
    respx.get("https://api.github.com/user/repos").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 11,
                    "owner": {"id": 99},
                    "full_name": "octocat/mostly-js",
                    "description": None,
                    "private": False,
                    "default_branch": "main",
                    "language": "JavaScript",
                }
            ],
        )
    )
    respx.get("https://api.github.com/repos/octocat/mostly-js/languages").mock(
        return_value=httpx.Response(200, json={"Python": 10, "JavaScript": 90})
    )

    repos = await _client().fetch_user_repos("gho_token", page=1)

    assert repos[0].python_percentage == 10.0
    assert repos[0].has_enough_python is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_user_repos_forwards_the_requested_page() -> None:
    route = respx.get("https://api.github.com/user/repos").mock(return_value=httpx.Response(200, json=[]))

    await _client().fetch_user_repos("gho_token", page=3)

    assert route.calls.last.request.url.params["page"] == "3"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_user_repos_raises_on_an_http_error() -> None:
    respx.get("https://api.github.com/user/repos").mock(return_value=httpx.Response(403, text="rate limited"))

    with pytest.raises(GitHubRepoFetchError):
        await _client().fetch_user_repos("gho_token", page=1)
