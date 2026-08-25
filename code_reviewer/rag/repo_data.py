"""
    Shared scoping/provenance value object for every RAG store.
"""
from dataclasses import dataclass


@dataclass
class RepoData:
    """Scoping and provenance shared by every file indexed from one commit of a repo."""

    repo_id: str
    commit_sha: str
    owner_id: str | None = None
