"""add branch and commit_sha to registered_repos, content to indexed_files

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-22

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("registered_repos", sa.Column("branch", sa.String(), nullable=True), schema="api")
    op.add_column("registered_repos", sa.Column("commit_sha", sa.String(), nullable=True), schema="api")
    op.execute("UPDATE api.registered_repos SET branch = default_branch WHERE branch IS NULL")
    op.alter_column("registered_repos", "branch", nullable=False, schema="api")
    op.add_column("indexed_files", sa.Column("content", sa.Text(), nullable=True), schema="api")


def downgrade() -> None:
    op.drop_column("indexed_files", "content", schema="api")
    op.drop_column("registered_repos", "commit_sha", schema="api")
    op.drop_column("registered_repos", "branch", schema="api")
