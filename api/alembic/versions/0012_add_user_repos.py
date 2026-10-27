"""add user_repos so several users can register the same repo

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-26

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_repos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("api.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("api.registered_repos.repo_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "repo_id"),
        schema="api",
    )
    op.create_index("ix_api_user_repos_repo_id", "user_repos", ["repo_id"], schema="api")
    op.execute(
        "INSERT INTO api.user_repos (user_id, repo_id) "
        "SELECT registered_by_user_id, repo_id FROM api.registered_repos"
    )


def downgrade() -> None:
    op.drop_index("ix_api_user_repos_repo_id", table_name="user_repos", schema="api")
    op.drop_table("user_repos", schema="api")
