"""
    Downloads one registered repo's default branch, walks its files, and dispatches each
    Python file to repo.file.index for RepoFileIndexConsumer to actually embed.
"""
import asyncio
import logging
import os
import tarfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from api.indexing.producer import RepoIndexProducer
from api.indexing.repo_completion_finalizer import RepoCompletionFinalizer
from api.indexing.topics import REPO_FILE_INDEX, REPO_FILE_PROGRESS, REPO_STATUS_PROGRESS
from api.integrations.github import GitHubOAuthClient
from api.schemas.indexing import RepoFileIndexMessage, RepoRegisteredMessage
from api.schemas.repos import RepoFileProgressMessage, RepoStatusProgressMessage
from api.security.token_cipher import TokenCipher

logger = logging.getLogger(__name__)

_EXCLUDED_DIR_NAMES = {".venv", "venv", "__pycache__", ".git", "node_modules"}
_MAX_INLINE_FILE_BYTES = 700_000  # headroom under Kafka's ~1MB default message size, after JSON overhead


class RepoIndexUserNotFoundError(Exception):
    """Raised when the user who registered a repo no longer exists."""


class RepoTarballLayoutError(Exception):
    """Raised when a downloaded tarball doesn't have GitHub's expected single top-level directory."""


@dataclass(frozen=True)
class RepoIndexerDependencies:
    """Collaborators RepoIndexer needs to fetch, walk, and dispatch a registered repo's files."""

    database_engine: DatabaseEngine
    http_client: httpx.AsyncClient
    token_cipher: TokenCipher
    github_client: GitHubOAuthClient
    repo_producer: RepoIndexProducer
    completion_finalizer: RepoCompletionFinalizer
    max_concurrent_file_dispatch: int


@dataclass(frozen=True)
class _IndexingContext:
    """Everything a single repo's walk pass needs, bundled to keep helper signatures short."""

    repo_msg: RepoRegisteredMessage
    commit_sha: str
    repo_root: str
    session: AsyncSession


class RepoIndexer:
    """Fetches a registered repo's content over GitHub, walks it, and dispatches each Python file for indexing."""

    def __init__(self, dependencies: RepoIndexerDependencies) -> None:
        self._dependencies = dependencies

    async def index_repo(self, repo_msg: RepoRegisteredMessage) -> None:
        async with self._dependencies.database_engine.new_session() as session:
            try:
                await self._fetch_and_index(repo_msg, session)
            except Exception as error:
                logger.error("Failed to index repo_id=%s", repo_msg.repo_id, exc_info=error)
                await session.rollback()
                await self._mark_repo_failed(repo_msg.repo_id, str(error), session)
                raise
            else:
                await self._dependencies.completion_finalizer.finalize_if_complete(repo_msg.repo_id, session)

    async def _fetch_and_index(self, repo_msg: RepoRegisteredMessage, session: AsyncSession) -> None:
        async with self._extracted_repo(repo_msg, session) as (commit_sha, repo_root):
            context = _IndexingContext(repo_msg=repo_msg, commit_sha=commit_sha, repo_root=repo_root, session=session)
            await self._index_repo_files(context)

    async def retry_failed_files(self, repo_msg: RepoRegisteredMessage) -> None:
        """Re-fetches the repo's tarball and re-dispatches only its currently-FAILED files."""
        async with self._dependencies.database_engine.new_session() as session:
            try:
                async with self._extracted_repo(repo_msg, session) as (commit_sha, repo_root):
                    context = _IndexingContext(
                        repo_msg=repo_msg, commit_sha=commit_sha, repo_root=repo_root, session=session
                    )
                    await self._redispatch_failed_files(context)
            except Exception as error:
                logger.error("Failed to retry failed files for repo_id=%s", repo_msg.repo_id, exc_info=error)
                await session.rollback()
                await self._mark_repo_failed(repo_msg.repo_id, str(error), session)
                raise
            else:
                await self._dependencies.completion_finalizer.finalize_if_complete(repo_msg.repo_id, session)

    @asynccontextmanager
    async def _extracted_repo(
        self, repo_msg: RepoRegisteredMessage, session: AsyncSession
    ) -> AsyncIterator[tuple[str, str]]:
        access_token = await self._fetch_access_token(repo_msg.registered_by_user_id, session)
        commit_sha = await self._dependencies.github_client.fetch_branch_commit_sha(
            access_token, repo_msg.full_name, repo_msg.default_branch
        )
        tarball = await self._dependencies.github_client.download_tarball(access_token, repo_msg.full_name, commit_sha)
        with TemporaryDirectory() as extract_dir:
            await asyncio.to_thread(_extract_tarball_safely, tarball, extract_dir)
            yield commit_sha, _find_extracted_repo_root(extract_dir)

    async def _fetch_access_token(self, user_id: int, session: AsyncSession) -> str:
        user = await session.get(User, user_id)
        if user is None:
            raise RepoIndexUserNotFoundError(f"No user with id={user_id} to index this repo")
        return self._dependencies.token_cipher.decrypt(user.encrypted_github_token)

    async def _index_repo_files(self, context: _IndexingContext) -> None:
        relative_paths = _walk_repo_files(context.repo_root)
        await self._start_indexing(context, total_files=len(relative_paths))
        semaphore = asyncio.Semaphore(self._dependencies.max_concurrent_file_dispatch)
        await asyncio.gather(
            *(self._dispatch_one_file(context, relative_path, semaphore) for relative_path in relative_paths)
        )

    async def _dispatch_one_file(
        self, context: _IndexingContext, relative_path: str, semaphore: asyncio.Semaphore
    ) -> None:
        async with semaphore:
            if not await self._should_dispatch(context, relative_path):
                return
            if not relative_path.endswith(".py"):
                await self._record_terminal(context, relative_path, IndexedFileStatus.SKIPPED, "not Python")
                return
            await self._queue_file_for_indexing(context, relative_path)

    async def _should_dispatch(self, context: _IndexingContext, relative_path: str) -> bool:
        """False when a resumed walk already has a row for this file, or the repo was paused mid-walk."""
        async with self._dependencies.database_engine.new_session() as session:
            repo = await session.scalar(
                select(RegisteredRepo).where(RegisteredRepo.repo_id == context.repo_msg.repo_id)
            )
            if repo is None or repo.status == RepoIndexStatus.PAUSED:
                return False
            existing = await session.scalar(
                select(IndexedFile).where(
                    IndexedFile.repo_id == context.repo_msg.repo_id, IndexedFile.file_path == relative_path
                )
            )
            return existing is None

    async def _start_indexing(self, context: _IndexingContext, total_files: int) -> None:
        repo = await context.session.scalar(
            select(RegisteredRepo).where(RegisteredRepo.repo_id == context.repo_msg.repo_id)
        )
        if repo is None:
            return
        repo.status = RepoIndexStatus.INDEXING
        repo.total_files_expected = total_files
        await context.session.commit()
        try:
            await self._dependencies.repo_producer.publish(
                REPO_STATUS_PROGRESS,
                RepoStatusProgressMessage(
                    repo_id=context.repo_msg.repo_id,
                    status=RepoIndexStatus.INDEXING,
                    status_reason=None,
                    total_files_expected=total_files,
                ),
                str(context.repo_msg.repo_id).encode(),
            )
        except Exception:
            # A lost notification, not a lost result — RegisteredRepo.status above is already committed.
            logger.exception("Failed to publish repo.status.progress for repo_id=%s", context.repo_msg.repo_id)

    async def _queue_file_for_indexing(self, context: _IndexingContext, relative_path: str) -> None:
        try:
            content = await asyncio.to_thread(_read_file, os.path.join(context.repo_root, relative_path))
        except Exception as error:
            await self._record_terminal(context, relative_path, IndexedFileStatus.FAILED, str(error))
            return
        if len(content.encode("utf-8")) > _MAX_INLINE_FILE_BYTES:
            await self._record_terminal(context, relative_path, IndexedFileStatus.SKIPPED, "too large to index inline")
            return
        message = RepoFileIndexMessage(
            repo_id=context.repo_msg.repo_id,
            owner_id=context.repo_msg.owner_id,
            commit_sha=context.commit_sha,
            file_path=relative_path,
            content=content,
        )
        async with self._dependencies.database_engine.new_session() as session:
            indexed_file = IndexedFile(
                repo_id=context.repo_msg.repo_id, file_path=relative_path, status=IndexedFileStatus.PENDING
            )
            session.add(indexed_file)
            await session.commit()
            await self._dispatch_or_mark_failed(context, indexed_file, message, session)

    async def _dispatch_or_mark_failed(
        self, context: _IndexingContext, indexed_file: IndexedFile, message: RepoFileIndexMessage, session: AsyncSession
    ) -> None:
        key = f"{context.repo_msg.repo_id}:{message.file_path}".encode()
        try:
            await self._dependencies.repo_producer.publish(REPO_FILE_INDEX, message, key)
        except Exception as error:
            # Unlike a lost progress notification, a lost dispatch means no consumer ever picks this up.
            logger.exception(
                "Failed to dispatch %s for repo_id=%s to repo.file.index", message.file_path, context.repo_msg.repo_id
            )
            indexed_file.status = IndexedFileStatus.FAILED
            indexed_file.status_reason = f"could not dispatch for indexing: {error}"
            await session.commit()
        else:
            logger.info(
                "Dispatched file_path=%s for repo_id=%s to repo.file.index", message.file_path, context.repo_msg.repo_id
            )

    async def _redispatch_failed_files(self, context: _IndexingContext) -> None:
        failed_paths = await self._get_failed_file_paths(context.repo_msg.repo_id)
        semaphore = asyncio.Semaphore(self._dependencies.max_concurrent_file_dispatch)
        await asyncio.gather(*(self._retry_one_file(context, path, semaphore) for path in failed_paths))

    async def _get_failed_file_paths(self, repo_id: int) -> list[str]:
        async with self._dependencies.database_engine.new_session() as session:
            rows = await session.scalars(
                select(IndexedFile.file_path).where(
                    IndexedFile.repo_id == repo_id, IndexedFile.status == IndexedFileStatus.FAILED
                )
            )
            return list(rows.all())

    async def _retry_one_file(
        self, context: _IndexingContext, relative_path: str, semaphore: asyncio.Semaphore
    ) -> None:
        async with semaphore:
            try:
                content = await asyncio.to_thread(_read_file, os.path.join(context.repo_root, relative_path))
            except Exception as error:
                await self._update_existing_terminal(context, relative_path, IndexedFileStatus.FAILED, str(error))
                return
            message = RepoFileIndexMessage(
                repo_id=context.repo_msg.repo_id,
                owner_id=context.repo_msg.owner_id,
                commit_sha=context.commit_sha,
                file_path=relative_path,
                content=content,
            )
            await self._dispatch_retry_or_mark_failed(context, relative_path, message)

    async def _dispatch_retry_or_mark_failed(
        self, context: _IndexingContext, relative_path: str, message: RepoFileIndexMessage
    ) -> None:
        key = f"{context.repo_msg.repo_id}:{relative_path}".encode()
        try:
            await self._dependencies.repo_producer.publish(REPO_FILE_INDEX, message, key)
        except Exception as error:
            # Same asymmetry as _dispatch_or_mark_failed: a lost dispatch means no consumer
            # ever re-embeds this file, so it must be recorded as FAILED, not just logged.
            logger.exception(
                "Failed to dispatch retry for %s repo_id=%s", relative_path, context.repo_msg.repo_id
            )
            await self._update_existing_terminal(
                context, relative_path, IndexedFileStatus.FAILED, f"could not dispatch retry: {error}"
            )
        else:
            logger.info("Dispatched retry for file_path=%s repo_id=%s", relative_path, context.repo_msg.repo_id)

    async def _update_existing_terminal(
        self, context: _IndexingContext, relative_path: str, status: IndexedFileStatus, reason: str
    ) -> None:
        """Like _record_terminal, but updates the row a retry is re-processing instead of inserting a new one."""
        async with self._dependencies.database_engine.new_session() as session:
            indexed_file = await session.scalar(
                select(IndexedFile).where(
                    IndexedFile.repo_id == context.repo_msg.repo_id, IndexedFile.file_path == relative_path
                )
            )
            if indexed_file is None:
                return
            indexed_file.status = status
            indexed_file.status_reason = reason
            await session.commit()
        try:
            await self._dependencies.repo_producer.publish(
                REPO_FILE_PROGRESS,
                RepoFileProgressMessage(
                    repo_id=context.repo_msg.repo_id, file_path=relative_path, status=status, status_reason=reason
                ),
                f"{context.repo_msg.repo_id}:{relative_path}".encode(),
            )
        except Exception:
            logger.exception(
                "Failed to publish repo.file.progress for repo_id=%s file_path=%s",
                context.repo_msg.repo_id, relative_path,
            )

    async def _record_terminal(
        self, context: _IndexingContext, relative_path: str, status: IndexedFileStatus, reason: str
    ) -> None:
        async with self._dependencies.database_engine.new_session() as session:
            session.add(
                IndexedFile(repo_id=context.repo_msg.repo_id, file_path=relative_path, status=status, status_reason=reason)
            )
            await session.commit()
        try:
            await self._dependencies.repo_producer.publish(
                REPO_FILE_PROGRESS,
                RepoFileProgressMessage(
                    repo_id=context.repo_msg.repo_id, file_path=relative_path, status=status, status_reason=reason
                ),
                f"{context.repo_msg.repo_id}:{relative_path}".encode(),
            )
        except Exception:
            # A lost notification, not a lost result — the terminal status above is already committed.
            logger.exception(
                "Failed to publish repo.file.progress for repo_id=%s file_path=%s",
                context.repo_msg.repo_id, relative_path,
            )

    async def _mark_repo_failed(self, repo_id: int, reason: str, session: AsyncSession) -> None:
        repo = await session.scalar(select(RegisteredRepo).where(RegisteredRepo.repo_id == repo_id))
        if repo is None:
            return
        repo.status = RepoIndexStatus.FAILED
        repo.status_reason = reason
        await session.commit()
        try:
            await self._dependencies.repo_producer.publish(
                REPO_STATUS_PROGRESS,
                RepoStatusProgressMessage(repo_id=repo_id, status=RepoIndexStatus.FAILED, status_reason=reason),
                str(repo_id).encode(),
            )
        except Exception:
            # A lost notification, not a lost result — repo.status above is already committed.
            logger.exception("Failed to publish repo.status.progress for repo_id=%s", repo_id)


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
