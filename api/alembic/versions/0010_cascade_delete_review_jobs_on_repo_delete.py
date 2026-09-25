"""cascade delete review_jobs when their repo is deleted

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-24

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("review_jobs_repo_id_fkey", "review_jobs", schema="api", type_="foreignkey")
    op.create_foreign_key(
        "review_jobs_repo_id_fkey",
        "review_jobs",
        "registered_repos",
        ["repo_id"],
        ["repo_id"],
        source_schema="api",
        referent_schema="api",
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("review_jobs_repo_id_fkey", "review_jobs", schema="api", type_="foreignkey")
    op.create_foreign_key(
        "review_jobs_repo_id_fkey",
        "review_jobs",
        "registered_repos",
        ["repo_id"],
        ["repo_id"],
        source_schema="api",
        referent_schema="api",
    )
