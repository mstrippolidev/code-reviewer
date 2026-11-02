"""
    Tests for GitHubPullRequestClient against faked HTTP responses (respx), no real network calls.
"""
import base64

import httpx
import pytest
import respx

from api.integrations.github import GitHubTokenRejectedError
from api.integrations.github_pull_requests import (
    FILES_PER_PAGE,
    GitHubFileUnreadableError,
    GitHubPullRequestClient,
    GitHubPullRequestFetchError,
    GitHubPullRequestNotFoundError,
)

FULL_NAME = "acme/api"
PR_NUMBER = 7
HEAD_SHA = "abc123"
TOKEN = "gho_token"
PULL_REQUEST_URL = f"https://api.github.com/repos/{FULL_NAME}/pulls/{PR_NUMBER}"
FILES_URL = f"{PULL_REQUEST_URL}/files"
CONTENTS_URL = f"https://api.github.com/repos/{FULL_NAME}/contents/src/app.py"


def _client() -> GitHubPullRequestClient:
    return GitHubPullRequestClient(httpx.AsyncClient())


def _pull_request_payload(**overrides) -> dict:
    payload = {
        "number": PR_NUMBER,
        "state": "open",
        "merged": False,
        "head": {"sha": HEAD_SHA},
        "base": {"ref": "main", "repo": {"id": 10, "full_name": "acme/api"}},
        "changed_files": 3,
    }
    return payload | overrides


def _file_payload(content: bytes = b"x = 1\n", **overrides) -> dict:
    payload = {"type": "file", "encoding": "base64", "content": base64.b64encode(content).decode()}
    return payload | overrides


def _files_page(count: int, prefix: str = "f") -> list[dict]:
    return [{"filename": f"{prefix}{index}.py", "status": "modified"} for index in range(count)]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pull_request_returns_the_head_commit() -> None:
    """Verify the commit to read files at comes from the pull request's head."""
    respx.get(PULL_REQUEST_URL).mock(return_value=httpx.Response(200, json=_pull_request_payload()))

    pull_request = await _client().fetch_pull_request(TOKEN, FULL_NAME, PR_NUMBER)

    assert pull_request.head_sha == HEAD_SHA


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pull_request_returns_the_base_branch() -> None:
    """Verify the branch the pull request targets is available for the tracked-branch check."""
    respx.get(PULL_REQUEST_URL).mock(return_value=httpx.Response(200, json=_pull_request_payload()))

    pull_request = await _client().fetch_pull_request(TOKEN, FULL_NAME, PR_NUMBER)

    assert pull_request.base_ref == "main"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pull_request_returns_the_target_repos_id_and_canonical_name() -> None:
    """Verify the repo is identified by GitHub's own id and spelling, not by the URL the user pasted."""
    payload = _pull_request_payload(base={"ref": "main", "repo": {"id": 765, "full_name": "Acme/API"}})
    respx.get(PULL_REQUEST_URL).mock(return_value=httpx.Response(200, json=payload))

    pull_request = await _client().fetch_pull_request(TOKEN, FULL_NAME, PR_NUMBER)

    assert (pull_request.base_repo_id, pull_request.base_repo_full_name) == (765, "Acme/API")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pull_request_returns_the_changed_file_count() -> None:
    """Verify the size check can use GitHub's own count without listing the files."""
    respx.get(PULL_REQUEST_URL).mock(return_value=httpx.Response(200, json=_pull_request_payload(changed_files=42)))

    pull_request = await _client().fetch_pull_request(TOKEN, FULL_NAME, PR_NUMBER)

    assert pull_request.changed_files == 42


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pull_request_reports_a_merged_pull_request() -> None:
    """Verify state and merged are both kept, since a merged pull request is also closed."""
    payload = _pull_request_payload(state="closed", merged=True)
    respx.get(PULL_REQUEST_URL).mock(return_value=httpx.Response(200, json=payload))

    pull_request = await _client().fetch_pull_request(TOKEN, FULL_NAME, PR_NUMBER)

    assert (pull_request.state, pull_request.merged) == ("closed", True)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pull_request_authenticates_with_the_callers_token() -> None:
    """Verify the read is made as the user, not with a shared credential."""
    route = respx.get(PULL_REQUEST_URL).mock(return_value=httpx.Response(200, json=_pull_request_payload()))

    await _client().fetch_pull_request(TOKEN, FULL_NAME, PR_NUMBER)

    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pull_request_raises_not_found_for_a_missing_pull_request() -> None:
    """Verify a pull request GitHub will not show is a not-found, which the route can turn into a 404."""
    respx.get(PULL_REQUEST_URL).mock(return_value=httpx.Response(404))

    with pytest.raises(GitHubPullRequestNotFoundError):
        await _client().fetch_pull_request(TOKEN, FULL_NAME, PR_NUMBER)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pull_request_raises_token_rejected_when_github_refuses_the_token() -> None:
    """Verify an expired GitHub login is reported so the user is asked to sign in again."""
    respx.get(PULL_REQUEST_URL).mock(return_value=httpx.Response(401))

    with pytest.raises(GitHubTokenRejectedError):
        await _client().fetch_pull_request(TOKEN, FULL_NAME, PR_NUMBER)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pull_request_raises_a_fetch_error_on_a_github_failure() -> None:
    """Verify a GitHub outage is not mistaken for a missing pull request."""
    respx.get(PULL_REQUEST_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(GitHubPullRequestFetchError):
        await _client().fetch_pull_request(TOKEN, FULL_NAME, PR_NUMBER)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pull_request_raises_a_fetch_error_when_github_is_unreachable() -> None:
    """Verify a network failure surfaces as a fetch error, not a raw httpx error."""
    respx.get(PULL_REQUEST_URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(GitHubPullRequestFetchError):
        await _client().fetch_pull_request(TOKEN, FULL_NAME, PR_NUMBER)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pull_request_raises_a_fetch_error_for_an_unexpected_payload() -> None:
    """Verify a payload missing a field the app relies on is reported, never passed on half-read."""
    respx.get(PULL_REQUEST_URL).mock(return_value=httpx.Response(200, json={"number": PR_NUMBER}))

    with pytest.raises(GitHubPullRequestFetchError):
        await _client().fetch_pull_request(TOKEN, FULL_NAME, PR_NUMBER)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_changed_files_returns_each_path_with_its_status() -> None:
    """Verify removed files are reported with their status, so the caller can leave them out."""
    page = [{"filename": "a.py", "status": "modified"}, {"filename": "b.py", "status": "removed"}]
    respx.get(FILES_URL).mock(return_value=httpx.Response(200, json=page))

    changed_files = await _client().fetch_changed_files(TOKEN, FULL_NAME, PR_NUMBER)

    assert [(file.path, file.status) for file in changed_files] == [("a.py", "modified"), ("b.py", "removed")]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_changed_files_reads_the_next_page_after_a_full_page() -> None:
    """Verify a pull request with more files than one page is read completely."""
    respx.get(FILES_URL, params={"page": "1", "per_page": str(FILES_PER_PAGE)}).mock(
        return_value=httpx.Response(200, json=_files_page(FILES_PER_PAGE, "first"))
    )
    respx.get(FILES_URL, params={"page": "2", "per_page": str(FILES_PER_PAGE)}).mock(
        return_value=httpx.Response(200, json=_files_page(2, "second"))
    )

    changed_files = await _client().fetch_changed_files(TOKEN, FULL_NAME, PR_NUMBER)

    assert len(changed_files) == FILES_PER_PAGE + 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_changed_files_stops_after_a_short_page() -> None:
    """Verify no request is wasted once GitHub returns fewer files than a full page."""
    route = respx.get(FILES_URL).mock(return_value=httpx.Response(200, json=_files_page(3)))

    await _client().fetch_changed_files(TOKEN, FULL_NAME, PR_NUMBER)

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_changed_files_raises_not_found_for_a_missing_pull_request() -> None:
    """Verify a pull request that disappears between calls is reported as not found."""
    respx.get(FILES_URL).mock(return_value=httpx.Response(404))

    with pytest.raises(GitHubPullRequestNotFoundError):
        await _client().fetch_changed_files(TOKEN, FULL_NAME, PR_NUMBER)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_changed_files_raises_a_fetch_error_for_an_unexpected_payload() -> None:
    """Verify a changed-file list in the wrong shape is reported, not skipped silently."""
    respx.get(FILES_URL).mock(return_value=httpx.Response(200, json=[{"name": "a.py"}]))

    with pytest.raises(GitHubPullRequestFetchError):
        await _client().fetch_changed_files(TOKEN, FULL_NAME, PR_NUMBER)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_file_at_ref_returns_the_decoded_text() -> None:
    """Verify the contents API's base64 payload comes back as source text."""
    respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200, json=_file_payload(b"def run():\n    pass\n")))

    content = await _client().fetch_file_at_ref(TOKEN, FULL_NAME, "src/app.py", HEAD_SHA)

    assert content == "def run():\n    pass\n"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_file_at_ref_reads_the_file_at_the_requested_commit() -> None:
    """Verify the file is read at the pull request's head commit, not at the default branch."""
    route = respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200, json=_file_payload()))

    await _client().fetch_file_at_ref(TOKEN, FULL_NAME, "src/app.py", HEAD_SHA)

    assert route.calls.last.request.url.params["ref"] == HEAD_SHA


@pytest.mark.asyncio
@respx.mock
async def test_fetch_file_at_ref_encodes_a_path_with_spaces() -> None:
    """Verify an unusual file name still reaches GitHub as a valid URL."""
    url = f"https://api.github.com/repos/{FULL_NAME}/contents/my%20dir/app.py"
    route = respx.get(url).mock(return_value=httpx.Response(200, json=_file_payload()))

    await _client().fetch_file_at_ref(TOKEN, FULL_NAME, "my dir/app.py", HEAD_SHA)

    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_fetch_file_at_ref_reports_a_file_too_large_for_the_contents_api() -> None:
    """Verify an oversized file is a per-file problem the caller can skip, not a failed fetch."""
    body = {"message": "This API returns blobs up to 1 MB in size.", "errors": [{"code": "too_large"}]}
    respx.get(CONTENTS_URL).mock(return_value=httpx.Response(403, json=body))

    with pytest.raises(GitHubFileUnreadableError):
        await _client().fetch_file_at_ref(TOKEN, FULL_NAME, "src/app.py", HEAD_SHA)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_file_at_ref_treats_another_403_as_a_fetch_error() -> None:
    """Verify a rate limit is not mistaken for an unreadable file, which would silently drop files."""
    respx.get(CONTENTS_URL).mock(return_value=httpx.Response(403, json={"message": "API rate limit exceeded"}))

    with pytest.raises(GitHubPullRequestFetchError):
        await _client().fetch_file_at_ref(TOKEN, FULL_NAME, "src/app.py", HEAD_SHA)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_file_at_ref_raises_a_fetch_error_for_a_missing_file() -> None:
    """Verify a changed file that GitHub cannot find at the head commit is reported, not skipped silently."""
    respx.get(CONTENTS_URL).mock(return_value=httpx.Response(404))

    with pytest.raises(GitHubPullRequestFetchError):
        await _client().fetch_file_at_ref(TOKEN, FULL_NAME, "src/app.py", HEAD_SHA)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_file_at_ref_reports_a_path_that_is_not_a_regular_file() -> None:
    """Verify a symlink or submodule ending in .py is skipped rather than parsed as source."""
    respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200, json={"type": "symlink", "target": "x.py"}))

    with pytest.raises(GitHubFileUnreadableError):
        await _client().fetch_file_at_ref(TOKEN, FULL_NAME, "src/app.py", HEAD_SHA)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_file_at_ref_reports_a_file_that_is_not_utf8_text() -> None:
    """Verify binary content named .py is skipped rather than reviewed."""
    respx.get(CONTENTS_URL).mock(return_value=httpx.Response(200, json=_file_payload(b"\xff\xfe\x00bad")))

    with pytest.raises(GitHubFileUnreadableError):
        await _client().fetch_file_at_ref(TOKEN, FULL_NAME, "src/app.py", HEAD_SHA)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_file_at_ref_raises_token_rejected_when_github_refuses_the_token() -> None:
    """Verify an expired GitHub login is reported while reading files too."""
    respx.get(CONTENTS_URL).mock(return_value=httpx.Response(401))

    with pytest.raises(GitHubTokenRejectedError):
        await _client().fetch_file_at_ref(TOKEN, FULL_NAME, "src/app.py", HEAD_SHA)
