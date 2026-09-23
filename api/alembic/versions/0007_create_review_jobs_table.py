"""create review_jobs table

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-22

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

REVIEW_JOB_STATUS = sa.Enum(
    "pending", "running", "completed", "failed", name="review_job_status", schema="api"
)


def upgrade() -> None:
    op.create_table(
        "review_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column(
            "repo_id", sa.BigInteger(), sa.ForeignKey("api.registered_repos.repo_id"), nullable=False
        ),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("api.users.id"), nullable=False),
        sa.Column("file_paths", sa.JSON(), nullable=False),
        sa.Column("status", REVIEW_JOB_STATUS, server_default="pending", nullable=False),
        sa.Column("status_reason", sa.String(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("review_id"),
        schema="api",
    )
    op.create_index("ix_api_review_jobs_review_id", "review_jobs", ["review_id"], schema="api")
    op.create_index("ix_api_review_jobs_repo_id", "review_jobs", ["repo_id"], schema="api")


def downgrade() -> None:
    op.drop_index("ix_api_review_jobs_repo_id", table_name="review_jobs", schema="api")
    op.drop_index("ix_api_review_jobs_review_id", table_name="review_jobs", schema="api")
    op.drop_table("review_jobs", schema="api")
    REVIEW_JOB_STATUS.drop(op.get_bind(), checkfirst=True)
