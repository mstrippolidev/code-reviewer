"""
    Represents one file as it arrives in a PR submission, before file
    selection and the per-file pipeline run on it.
"""
from pydantic import BaseModel, Field

from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash_store import LocatedChunk
from code_reviewer.schemas.review import ReviewScope, SizeStatus


class SubmittedFile(BaseModel):
    file_path: str = Field(description="Path to this file, relative to the repo root.")
    content: str = Field(description="The file's raw source content, as submitted.")

class PreparedFile(BaseModel):
    """Represents one file after it has been selected for review and
    prepared for the per-file pipeline run on it.
    """
    source_file: SubmittedFile
    test_files: list[SubmittedFile] = []
    size_status: SizeStatus
    review_scope: ReviewScope = ReviewScope.FULL
    repo_data: RepoData | None = Field(
        default=None,
        description=(
            "Repo scoping for this submission, shared by every file in it. "
            "None for a standalone review with no repo context, in which "
            "case the ARCH/COUP evidence hop falls back to single-file judgment."
        ),
    )
    intra_pr_duplicates: list[list[LocatedChunk]] = Field(
        default_factory=list,
        description=(
            "This file's slice of the PR's intra-PR duplicate groups, "
            "computed once for the whole submission since a group can span "
            "files this file's own pipeline pass never otherwise sees. "
            "Empty when this file shares no structural duplicate with "
            "anything else in the PR."
        ),
    )