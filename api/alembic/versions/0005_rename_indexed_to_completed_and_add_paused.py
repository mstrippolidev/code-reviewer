"""rename indexed to completed and add paused to repo_index_status

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-21

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside alembic's default transaction on every
    # Postgres version, so both statements run in an autocommit block regardless of version.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE api.repo_index_status RENAME VALUE 'indexed' TO 'completed'")
        op.execute("ALTER TYPE api.repo_index_status ADD VALUE IF NOT EXISTS 'paused'")


def downgrade() -> None:
    # Postgres cannot remove a value from an enum type, so 'paused' stays on downgrade.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE api.repo_index_status RENAME VALUE 'completed' TO 'indexed'")
