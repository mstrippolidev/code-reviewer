"""create registered_repos table

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

REPO_INDEX_STATUS = sa.Enum("pending", "indexing", "indexed", "failed", name="repo_index_status", schema="api")


def upgrade() -> None:
    op.create_table(
        "registered_repos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("default_branch", sa.String(), nullable=False),
        sa.Column("registered_by_user_id", sa.Integer(), sa.ForeignKey("api.users.id"), nullable=False),
        sa.Column("status", REPO_INDEX_STATUS, server_default="pending", nullable=False),
        sa.Column("status_reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("repo_id"),
        schema="api",
    )
    op.create_index("ix_api_registered_repos_repo_id", "registered_repos", ["repo_id"], schema="api")
    op.create_index("ix_api_registered_repos_owner_id", "registered_repos", ["owner_id"], schema="api")


def downgrade() -> None:
    op.drop_index("ix_api_registered_repos_owner_id", table_name="registered_repos", schema="api")
    op.drop_index("ix_api_registered_repos_repo_id", table_name="registered_repos", schema="api")
    op.drop_table("registered_repos", schema="api")
    REPO_INDEX_STATUS.drop(op.get_bind(), checkfirst=True)
