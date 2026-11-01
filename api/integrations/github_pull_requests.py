"""
    GitHub pull request reads: a pull request's metadata, the files it changes, and a file's content at a commit.
"""
import base64
import binascii
import urllib.parse

import httpx

from api.integrations.github import REPO_INDEXING_REQUEST_TIMEOUT_SECONDS, GitHubTokenRejectedError
from api.schemas.github import GitHubPullRequest, GitHubPullRequestFile

PULL_REQUEST_URL_TEMPLATE = "https://api.github.com/repos/{full_name}/pulls/{number}"
PULL_REQUEST_FILES_URL_TEMPLATE = "https://api.github.com/repos/{full_name}/pulls/{number}/files"
FILE_CONTENT_URL_TEMPLATE = "https://api.github.com/repos/{full_name}/contents/{path}"

FILES_PER_PAGE = 100
TOO_LARGE_ERROR_CODE = "too_large"


class GitHubPullRequestNotFoundError(Exception):
    """Raised when GitHub has no such pull request, or the token's owner cannot see it."""


class GitHubPullRequestFetchError(Exception):
    """Raised when GitHub cannot be reached or answers a pull request read with an unexpected error."""


class GitHubFileUnreadableError(Exception):
    """Raised when a file at a commit cannot be read as text: too large, not a regular file, or not valid UTF-8."""


class GitHubPullRequestClient:
    """Reads pull requests with a user's own GitHub token, over the app's shared HTTP client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch_pull_request(self, access_token: str, full_name: str, number: int) -> GitHubPullRequest:
        """The pull request's state, head commit, base branch and changed-file count.

        Raises:
            GitHubPullRequestNotFoundError: If the pull request does not exist or is not visible to the token.
            GitHubTokenRejectedError: If GitHub no longer accepts the token.
            GitHubPullRequestFetchError: If GitHub cannot be reached or answers unexpectedly.
        """
        url = PULL_REQUEST_URL_TEMPLATE.format(full_name=full_name, number=number)
        response = await self._get(url, access_token)
        if response.status_code == httpx.codes.NOT_FOUND:
            raise GitHubPullRequestNotFoundError(f"Pull request {number} was not found in {full_name}")
        return self._parse_pull_request(response)

    async def fetch_changed_files(self, access_token: str, full_name: str, number: int) -> list[GitHubPullRequestFile]:
        """Every file the pull request changes, removed ones included, read page by page until a short page.

        Raises:
            GitHubPullRequestNotFoundError: If the pull request does not exist or is not visible to the token.
            GitHubTokenRejectedError: If GitHub no longer accepts the token.
            GitHubPullRequestFetchError: If GitHub cannot be reached or answers unexpectedly.
        """
        url = PULL_REQUEST_FILES_URL_TEMPLATE.format(full_name=full_name, number=number)
        changed_files: list[GitHubPullRequestFile] = []
        page = 1
        while True:
            page_files = await self._fetch_files_page(url, access_token, page)
            changed_files.extend(page_files)
            if len(page_files) < FILES_PER_PAGE:
                return changed_files
            page += 1

    async def fetch_file_at_ref(self, access_token: str, full_name: str, path: str, ref: str) -> str:
        """The file's text as it is at the given commit.

        Raises:
            GitHubFileUnreadableError: If the file is too large, not a regular file, or not valid UTF-8.
            GitHubTokenRejectedError: If GitHub no longer accepts the token.
            GitHubPullRequestFetchError: If GitHub cannot be reached, has no such file at that commit,
                or answers unexpectedly.
        """
        url = FILE_CONTENT_URL_TEMPLATE.format(full_name=full_name, path=urllib.parse.quote(path))
        response = await self._get(url, access_token, params={"ref": ref}, allow_forbidden=True)
        if response.status_code == httpx.codes.NOT_FOUND:
            raise GitHubPullRequestFetchError(f"{path} was not found at {ref} in {full_name}")
        if response.status_code == httpx.codes.FORBIDDEN:
            raise self._to_forbidden_error(response, path)
        return self._decode_file(response, path)

    async def _fetch_files_page(self, url: str, access_token: str, page: int) -> list[GitHubPullRequestFile]:
        """One page of the changed-file list; a missing pull request here is the same not-found as for the pull request."""
        response = await self._get(url, access_token, params={"page": page, "per_page": FILES_PER_PAGE})
        if response.status_code == httpx.codes.NOT_FOUND:
            raise GitHubPullRequestNotFoundError("Pull request was not found while listing its files")
        try:
            return [GitHubPullRequestFile(path=item["filename"], status=item["status"]) for item in response.json()]
        except (ValueError, KeyError, TypeError) as error:
            raise GitHubPullRequestFetchError("GitHub sent an unexpected changed-file list") from error

    async def _get(
        self, url: str, access_token: str, params: dict | None = None, allow_forbidden: bool = False
    ) -> httpx.Response:
        """Sends one authenticated read and returns the response unless GitHub's answer is an error other than 404.

        A 404 is returned for the caller to interpret, and so is a 403 when `allow_forbidden` is set, because
        the contents API uses a 403 to say a file is too large.
        """
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
        try:
            response = await self._client.get(
                url, headers=headers, params=params, timeout=REPO_INDEXING_REQUEST_TIMEOUT_SECONDS
            )
        except httpx.HTTPError as error:
            raise GitHubPullRequestFetchError("Could not reach GitHub to read the pull request") from error
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise GitHubTokenRejectedError("GitHub rejected the access token")
        accepted = response.is_success or response.status_code == httpx.codes.NOT_FOUND
        if not accepted and not (allow_forbidden and response.status_code == httpx.codes.FORBIDDEN):
            raise GitHubPullRequestFetchError(f"GitHub answered {response.status_code} for {url}")
        return response

    def _parse_pull_request(self, response: httpx.Response) -> GitHubPullRequest:
        """Turns GitHub's pull request JSON into the model, or raises if a field this app relies on is missing."""
        try:
            payload = response.json()
            return GitHubPullRequest(
                number=payload["number"],
                state=payload["state"],
                merged=payload["merged"],
                head_sha=payload["head"]["sha"],
                base_ref=payload["base"]["ref"],
                base_repo_id=payload["base"]["repo"]["id"],
                base_repo_full_name=payload["base"]["repo"]["full_name"],
                changed_files=payload["changed_files"],
            )
        except (ValueError, KeyError, TypeError) as error:
            raise GitHubPullRequestFetchError("GitHub sent an unexpected pull request payload") from error

    def _to_forbidden_error(self, response: httpx.Response, path: str) -> Exception:
        """A 403 that says `too_large` means this one file cannot be read; any other 403 is GitHub refusing, such as a rate limit."""
        try:
            error_codes = [error.get("code") for error in response.json().get("errors", [])]
        except (ValueError, AttributeError):
            error_codes = []
        if TOO_LARGE_ERROR_CODE in error_codes:
            return GitHubFileUnreadableError(f"{path} is too large to read through the GitHub contents API")
        return GitHubPullRequestFetchError("GitHub refused the file read (403), possibly a rate limit")

    def _decode_file(self, response: httpx.Response, path: str) -> str:
        """Decodes the contents API's base64 payload into text, or raises if it is not a regular UTF-8 text file."""
        try:
            payload = response.json()
        except ValueError as error:
            raise GitHubPullRequestFetchError("GitHub sent an unreadable file payload") from error
        if not isinstance(payload, dict) or payload.get("type") != "file" or payload.get("encoding") != "base64":
            raise GitHubFileUnreadableError(f"{path} is not a regular file GitHub can return as text")
        try:
            return base64.b64decode(payload["content"]).decode("utf-8")
        except (KeyError, binascii.Error, UnicodeDecodeError) as error:
            raise GitHubFileUnreadableError(f"{path} is not valid UTF-8 text") from error
