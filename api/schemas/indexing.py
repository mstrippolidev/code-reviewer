from pydantic import BaseModel


class RepoRegisteredMessage(BaseModel):
    """Kafka message payload published to the repo.registered topic."""

    repo_id: int
    owner_id: int
    full_name: str
    default_branch: str
    registered_by_user_id: int
