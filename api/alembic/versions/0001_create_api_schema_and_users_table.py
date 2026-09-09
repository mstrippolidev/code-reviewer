"""create api schema and users table

Revision ID: 0001
Revises:
Create Date: 2026-09-08

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS api")
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("github_username", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("encrypted_github_token", sa.String(), nullable=False),
        sa.Column("github_granted_scopes", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("github_id"),
        schema="api",
    )
    op.create_index("ix_api_users_github_id", "users", ["github_id"], schema="api")


def downgrade() -> None:
    op.drop_index("ix_api_users_github_id", table_name="users", schema="api")
    op.drop_table("users", schema="api")
    op.execute("DROP SCHEMA IF EXISTS api CASCADE")
