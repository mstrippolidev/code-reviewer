"""
    Turns a registered repo row into the scoping value object the RAG layer expects.
"""
from api.db.models.registered_repo import RegisteredRepo
from code_reviewer.rag.repo_data import RepoData


def repo_data_of(repo: RegisteredRepo) -> RepoData:
    """The scoping the pipeline searches within: this repo, its owner, and the commit its index reflects."""
    return RepoData(repo_id=str(repo.repo_id), owner_id=str(repo.owner_id), commit_sha=repo.commit_sha)
