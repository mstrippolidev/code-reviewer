"""add agent_entries to review_jobs

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-23

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("review_jobs", sa.Column("agent_entries", sa.JSON(), nullable=True), schema="api")


def downgrade() -> None:
    op.drop_column("review_jobs", "agent_entries", schema="api")
