"""
    Downloads one registered repo's default branch and indexes its Python files.
"""
import asyncio
import logging
import os
import tarfile
from dataclasses import dataclass
from io import BytesIO
from tempfile import TemporaryDirectory

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.engine import DatabaseEngine
from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.integrations.github import GitHubOAuthClient
from api.schemas.indexing import RepoRegisteredMessage
from api.security.token_cipher import TokenCipher
from code_reviewer.rag.indexer import LlamaIndexRagManager
from code_reviewer.rag.repo_data import RepoData

logger = logging.getLogger(__name__)

_EXCLUDED_DIR_NAMES = {".venv", "venv", "__pycache__", ".git", "node_modules"}


class RepoIndexUserNotFoundError(Exception):
    """Raised when the user who registered a repo no longer exists."""


class RepoTarballLayoutError(Exception):
    """Raised when a downloaded tarball doesn't have GitHub's expected single top-level directory."""


@dataclass(frozen=True)
class RepoIndexerDependencies:
    """Collaborators RepoIndexer needs to fetch, walk, and index a registered repo."""

    database_engine: DatabaseEngine
    http_client: httpx.AsyncClient
    token_cipher: TokenCipher
    github_client: GitHubOAuthClient
    rag_manager: LlamaIndexRagManager


@dataclass(frozen=True)
class _IndexingContext:
    """Everything a single repo's per-file indexing pass needs, bundled to keep helper signatures short."""

    repo_msg: RepoRegisteredMessage
    commit_sha: str
    repo_root: str
    session: AsyncSession


class RepoIndexer:
    """Fetches a registered repo's content over GitHub and indexes every Python file into code_reviewer.rag."""

    def __init__(self, dependencies: RepoIndexerDependencies) -> None:
        self._dependencies = dependencies

    async def index_repo(self, repo_msg: RepoRegisteredMessage) -> None:
        async with self._dependencies.database_engine.new_session() as session:
            try:
                await self._fetch_and_index(repo_msg, session)
            except Exception as error:
                logger.error("Failed to index repo_id=%s", repo_msg.repo_id, exc_info=error)
                await self._mark_repo_failed(repo_msg.repo_id, str(error), session)
                raise
            else:
                await self._mark_repo_indexed(repo_msg.repo_id, session)

    async def _fetch_and_index(self, repo_msg: RepoRegisteredMessage, session: AsyncSession) -> None:
        access_token = await self._fetch_access_token(repo_msg.registered_by_user_id, session)
        commit_sha = await self._dependencies.github_client.fetch_branch_commit_sha(
            access_token, repo_msg.full_name, repo_msg.default_branch
        )
        tarball = await self._dependencies.github_client.download_tarball(access_token, repo_msg.full_name, commit_sha)
        with TemporaryDirectory() as extract_dir:
            await asyncio.to_thread(_extract_tarball_safely, tarball, extract_dir)
            repo_root = _find_extracted_repo_root(extract_dir)
            context = _IndexingContext(repo_msg=repo_msg, commit_sha=commit_sha, repo_root=repo_root, session=session)
            await self._index_repo_files(context)

    async def _fetch_access_token(self, user_id: int, session: AsyncSession) -> str:
        user = await session.get(User, user_id)
        if user is None:
            raise RepoIndexUserNotFoundError(f"No user with id={user_id} to index this repo")
        return self._dependencies.token_cipher.decrypt(user.encrypted_github_token)

    async def _index_repo_files(self, context: _IndexingContext) -> None:
        repo_data = RepoData(
            repo_id=str(context.repo_msg.repo_id),
            commit_sha=context.commit_sha,
            owner_id=str(context.repo_msg.owner_id),
        )
        for relative_path in _walk_repo_files(context.repo_root):
            if not relative_path.endswith(".py"):
                await self._record_skip(context, relative_path)
                continue
            await self._index_one_file(context, repo_data, relative_path)

    async def _record_skip(self, context: _IndexingContext, relative_path: str) -> None:
        context.session.add(
            IndexedFile(
                repo_id=context.repo_msg.repo_id,
                file_path=relative_path,
                status=IndexedFileStatus.SKIPPED,
                status_reason="not Python",
            )
        )
        await context.session.commit()

    async def _index_one_file(self, context: _IndexingContext, repo_data: RepoData, relative_path: str) -> None:
        indexed_file = IndexedFile(
            repo_id=context.repo_msg.repo_id,
            file_path=relative_path,
            status=IndexedFileStatus.PROCESSING,
        )
        context.session.add(indexed_file)
        await context.session.commit()
        try:
            content = await asyncio.to_thread(_read_file, os.path.join(context.repo_root, relative_path))
            await asyncio.to_thread(self._dependencies.rag_manager.index_file, repo_data, relative_path, content)
        except Exception as error:
            logger.error(
                "Failed to index %s for repo_id=%s", relative_path, context.repo_msg.repo_id, exc_info=error
            )
            indexed_file.status = IndexedFileStatus.FAILED
            indexed_file.status_reason = str(error)
        else:
            indexed_file.status = IndexedFileStatus.INDEXED
        await context.session.commit()

    async def _mark_repo_indexed(self, repo_id: int, session: AsyncSession) -> None:
        await self._set_repo_status(repo_id, RepoIndexStatus.INDEXED, None, session)

    async def _mark_repo_failed(self, repo_id: int, reason: str, session: AsyncSession) -> None:
        await self._set_repo_status(repo_id, RepoIndexStatus.FAILED, reason, session)

    async def _set_repo_status(
        self, repo_id: int, status: RepoIndexStatus, reason: str | None, session: AsyncSession
    ) -> None:
        repo = await session.scalar(select(RegisteredRepo).where(RegisteredRepo.repo_id == repo_id))
        if repo is None:
            return
        repo.status = status
        repo.status_reason = reason
        await session.commit()


def _extract_tarball_safely(tarball: bytes, extract_dir: str) -> None:
    with tarfile.open(fileobj=BytesIO(tarball), mode="r:gz") as archive:
        safe_members = [member for member in archive.getmembers() if _is_safe_tar_member(member, extract_dir)]
        archive.extractall(path=extract_dir, members=safe_members)


def _is_safe_tar_member(member: tarfile.TarInfo, extract_dir: str) -> bool:
    resolved_path = os.path.realpath(os.path.join(extract_dir, member.name))
    return resolved_path.startswith(os.path.realpath(extract_dir) + os.sep)


def _find_extracted_repo_root(extract_dir: str) -> str:
    entries = os.listdir(extract_dir)
    if len(entries) != 1:
        raise RepoTarballLayoutError(f"Expected exactly one top-level directory in the tarball, found {entries}")
    return os.path.join(extract_dir, entries[0])


def _walk_repo_files(repo_root: str) -> list[str]:
    relative_paths = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [name for name in dirnames if name not in _EXCLUDED_DIR_NAMES and not name.startswith(".")]
        for filename in filenames:
            absolute_path = os.path.join(dirpath, filename)
            relative_paths.append(os.path.relpath(absolute_path, repo_root))
    return relative_paths


def _read_file(path: str) -> str:
    with open(path, encoding="utf-8") as file:
        return file.read()
