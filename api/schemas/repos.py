from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.db.models.indexed_file import IndexedFileStatus
from api.db.models.registered_repo import RepoIndexStatus


class RegisterRepoRequest(BaseModel):
    """What the client claims about the repo to register; verified against GitHub before it's trusted."""

    repo_id: int
    full_name: str
    branch: str | None = None


class SwitchBranchRequest(BaseModel):
    """The branch a registered repo should re-index against, replacing whatever is currently indexed."""

    branch: str


class RegisteredRepoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    repo_id: int
    owner_id: int
    full_name: str
    default_branch: str
    branch: str
    commit_sha: str | None
    status: RepoIndexStatus
    status_reason: str | None
    total_files_expected: int | None
    created_at: datetime


class IndexedFileRead(BaseModel):
    """
        Show state of a file in a repo.
    """
    model_config = ConfigDict(from_attributes=True)

    file_path: str
    status: IndexedFileStatus
    status_reason: str | None
    indexed_at: datetime | None

class IndexedFileContentRead(BaseModel):
    """The stored source of one indexed file, for a client rendering it alongside a review."""

    model_config = ConfigDict(from_attributes=True)

    file_path: str
    content: str


class RepoFileProgressMessage(BaseModel):
    """Schema for the progress bar SSE"""
    repo_id: int
    file_path: str
    status: IndexedFileStatus
    status_reason: str | None


class RepoStatusProgressMessage(BaseModel):
    """Published on every repo-level status change; the SSE route relays it live and stops on a terminal state."""
    repo_id: int
    status: RepoIndexStatus
    status_reason: str | None
    total_files_expected: int | None = None
