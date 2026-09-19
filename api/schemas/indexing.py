from pydantic import BaseModel


class RepoRegisteredMessage(BaseModel):
    """Kafka message payload published to the repo.registered topic."""

    repo_id: int
    owner_id: int
    full_name: str
    default_branch: str
    registered_by_user_id: int


class RepoFileIndexMessage(BaseModel):
    """Kafka message payload published to the repo.file.index topic; one file's content to be indexed."""

    repo_id: int
    owner_id: int
    commit_sha: str
    file_path: str
    content: str
