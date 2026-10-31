"""add the requested agents to review_jobs

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-30

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("review_jobs", sa.Column("agents", sa.JSON(), nullable=True), schema="api")


def downgrade() -> None:
    op.drop_column("review_jobs", "agents", schema="api")
