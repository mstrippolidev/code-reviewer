"""create similar_code_searches table

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-31

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

SIMILAR_CODE_SEARCH_STATUS = sa.Enum(
    "pending", "running", "completed", "rejected", "failed", name="similar_code_search_status", schema="api"
)


def upgrade() -> None:
    op.create_table(
        "similar_code_searches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_id", sa.Uuid(), nullable=False),
        sa.Column(
            "repo_id",
            sa.BigInteger(),
            sa.ForeignKey("api.registered_repos.repo_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("api.users.id"), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("status", SIMILAR_CODE_SEARCH_STATUS, server_default="pending", nullable=False),
        sa.Column("status_reason", sa.String(), nullable=True),
        sa.Column("incidents", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("search_id"),
        schema="api",
    )
    op.create_index(
        "ix_api_similar_code_searches_search_id", "similar_code_searches", ["search_id"], schema="api"
    )
    op.create_index("ix_api_similar_code_searches_repo_id", "similar_code_searches", ["repo_id"], schema="api")


def downgrade() -> None:
    op.drop_index("ix_api_similar_code_searches_repo_id", table_name="similar_code_searches", schema="api")
    op.drop_index("ix_api_similar_code_searches_search_id", table_name="similar_code_searches", schema="api")
    op.drop_table("similar_code_searches", schema="api")
    SIMILAR_CODE_SEARCH_STATUS.drop(op.get_bind(), checkfirst=True)
