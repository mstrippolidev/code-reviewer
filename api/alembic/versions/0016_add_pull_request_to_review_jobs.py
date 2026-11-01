"""add the pull request number and head commit to review_jobs

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-31

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("review_jobs", sa.Column("pr_number", sa.Integer(), nullable=True), schema="api")
    op.add_column("review_jobs", sa.Column("head_sha", sa.String(), nullable=True), schema="api")


def downgrade() -> None:
    op.drop_column("review_jobs", "head_sha", schema="api")
    op.drop_column("review_jobs", "pr_number", schema="api")
