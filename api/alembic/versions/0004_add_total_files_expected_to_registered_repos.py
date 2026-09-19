"""add total_files_expected to registered_repos

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-17

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "registered_repos",
        sa.Column("total_files_expected", sa.Integer(), nullable=True),
        schema="api",
    )


def downgrade() -> None:
    op.drop_column("registered_repos", "total_files_expected", schema="api")
