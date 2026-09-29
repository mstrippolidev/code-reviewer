"""add guest_sessions and guest_review_files tables and allow repo-less guest review_jobs

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-26

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guest_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="api",
    )
    op.alter_column("review_jobs", "repo_id", nullable=True, schema="api")
    op.alter_column("review_jobs", "requested_by_user_id", nullable=True, schema="api")
    op.add_column(
        "review_jobs",
        sa.Column(
            "guest_session_id",
            sa.Integer(),
            sa.ForeignKey("api.guest_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        schema="api",
    )
    op.create_index("ix_api_review_jobs_guest_session_id", "review_jobs", ["guest_session_id"], schema="api")
    op.create_table(
        "guest_review_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "review_job_id",
            sa.Integer(),
            sa.ForeignKey("api.review_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.UniqueConstraint("review_job_id", "file_path"),
        schema="api",
    )
    op.create_index("ix_api_guest_review_files_review_job_id", "guest_review_files", ["review_job_id"], schema="api")


def downgrade() -> None:
    op.drop_index("ix_api_guest_review_files_review_job_id", table_name="guest_review_files", schema="api")
    op.drop_table("guest_review_files", schema="api")
    op.execute("DELETE FROM api.review_jobs WHERE guest_session_id IS NOT NULL")
    op.drop_index("ix_api_review_jobs_guest_session_id", table_name="review_jobs", schema="api")
    op.drop_column("review_jobs", "guest_session_id", schema="api")
    op.alter_column("review_jobs", "requested_by_user_id", nullable=False, schema="api")
    op.alter_column("review_jobs", "repo_id", nullable=False, schema="api")
    op.drop_table("guest_sessions", schema="api")
