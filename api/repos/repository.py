from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo
from api.db.models.user_repo import UserRepo
from api.repos.errors import IndexedFileNotFoundError, RepoAlreadyRegisteredError, RepoNotFoundError


class RegisteredRepoRepository:
    """Reads and writes registered repos and their indexed files on behalf of the repo routes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_registered_by(self, user_id: int) -> list[RegisteredRepo]:
        result = await self._session.scalars(
            select(RegisteredRepo)
            .join(UserRepo, UserRepo.repo_id == RegisteredRepo.repo_id)
            .where(UserRepo.user_id == user_id)
        )
        return list(result.all())

    async def is_linked(self, user_id: int, repo_id: int) -> bool:
        link_id = await self._session.scalar(
            select(UserRepo.id).where(UserRepo.user_id == user_id, UserRepo.repo_id == repo_id).limit(1)
        )
        return link_id is not None

    async def add_link(self, user_id: int, repo_id: int) -> None:
        if await self.is_linked(user_id, repo_id):
            return
        self._session.add(UserRepo(user_id=user_id, repo_id=repo_id))

    async def remove_link(self, user_id: int, repo_id: int) -> None:
        await self._session.execute(delete(UserRepo).where(UserRepo.user_id == user_id, UserRepo.repo_id == repo_id))

    async def find_by_full_name(self, full_name: str) -> RegisteredRepo:
        statement = select(RegisteredRepo).where(func.lower(RegisteredRepo.full_name) == full_name.lower())
        repo = await self._session.scalar(statement)
        if repo is None:
            raise RepoNotFoundError("Could not find the repo")
        return repo

    async def list_indexed_files(self, repo_id: int) -> list[IndexedFile]:
        result = await self._session.scalars(select(IndexedFile).where(IndexedFile.repo_id == repo_id))
        return list(result.all())

    async def find_indexed_content(self, repo_id: int, file_path: str) -> IndexedFile:
        file = await self._session.scalar(
            select(IndexedFile).where(
                IndexedFile.repo_id == repo_id,
                IndexedFile.file_path == file_path,
                IndexedFile.status == IndexedFileStatus.INDEXED,
            )
        )
        if file is None or file.content is None:
            raise IndexedFileNotFoundError(f"No indexed content for {file_path} in this repo")
        return file

    async def has_failed_files(self, repo_id: int) -> bool:
        failed_file_id = await self._session.scalar(
            select(IndexedFile.id)
            .where(IndexedFile.repo_id == repo_id, IndexedFile.status == IndexedFileStatus.FAILED)
            .limit(1)
        )
        return failed_file_id is not None

    async def is_registered(self, repo_id: int) -> bool:
        registered_id = await self._session.scalar(
            select(RegisteredRepo.id).where(RegisteredRepo.repo_id == repo_id).limit(1)
        )
        return registered_id is not None

    async def find_by_repo_id(self, repo_id: int) -> RegisteredRepo:
        repo = await self._session.scalar(select(RegisteredRepo).where(RegisteredRepo.repo_id == repo_id))
        if repo is None:
            raise RepoNotFoundError("Could not find the repo")
        return repo

    async def add(self, registered: RegisteredRepo) -> None:
        self._session.add(registered)
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise RepoAlreadyRegisteredError() from error
        self._session.add(UserRepo(user_id=registered.registered_by_user_id, repo_id=registered.repo_id))
        await self._session.commit()
        await self._session.refresh(registered)

    async def remove(self, repo: RegisteredRepo) -> None:
        await self._session.delete(repo)

    async def delete_indexed_files(self, repo_id: int) -> None:
        await self._session.execute(delete(IndexedFile).where(IndexedFile.repo_id == repo_id))

    async def commit_changes(self) -> None:
        await self._session.commit()
