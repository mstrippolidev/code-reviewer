"""create indexed_files table

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

INDEXED_FILE_STATUS = sa.Enum(
    "pending", "processing", "indexed", "skipped", "failed", name="indexed_file_status", schema="api"
)


def upgrade() -> None:
    op.create_table(
        "indexed_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.BigInteger(), sa.ForeignKey("api.registered_repos.repo_id"), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("status", INDEXED_FILE_STATUS, server_default="pending", nullable=False),
        sa.Column("status_reason", sa.String(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("repo_id", "file_path"),
        schema="api",
    )
    op.create_index("ix_api_indexed_files_repo_id", "indexed_files", ["repo_id"], schema="api")


def downgrade() -> None:
    op.drop_index("ix_api_indexed_files_repo_id", table_name="indexed_files", schema="api")
    op.drop_table("indexed_files", schema="api")
    INDEXED_FILE_STATUS.drop(op.get_bind(), checkfirst=True)
