"""create exemplar_promotions table

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-12

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

PROMOTION_OUTCOME = sa.Enum("promoted", "rejected", "needs_review", name="promotion_outcome", schema="api")


def upgrade() -> None:
    op.create_table(
        "exemplar_promotions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("api.registered_repos.repo_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("code_key", sa.String(), nullable=False),
        sa.Column("content_digest", sa.String(), nullable=False),
        sa.Column("outcome", PROMOTION_OUTCOME, nullable=False),
        sa.Column("decided_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "repo_id", "file_path", "code_key", "content_digest", name="uq_exemplar_promotions_content"
        ),
        schema="api",
    )
    op.create_index("ix_api_exemplar_promotions_repo_id", "exemplar_promotions", ["repo_id"], schema="api")


def downgrade() -> None:
    op.drop_index("ix_api_exemplar_promotions_repo_id", table_name="exemplar_promotions", schema="api")
    op.drop_table("exemplar_promotions", schema="api")
    PROMOTION_OUTCOME.drop(op.get_bind(), checkfirst=True)
