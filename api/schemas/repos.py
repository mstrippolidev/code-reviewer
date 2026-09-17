from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.db.models.indexed_file import IndexedFileStatus
from api.db.models.registered_repo import RepoIndexStatus


class RegisterRepoRequest(BaseModel):
    """What the client claims about the repo to register; verified against GitHub before it's trusted."""

    repo_id: int
    full_name: str


class RegisteredRepoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    repo_id: int
    owner_id: int
    full_name: str
    default_branch: str
    status: RepoIndexStatus
    status_reason: str | None
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
