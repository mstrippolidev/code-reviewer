"""create calibration tables

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calibration_pairs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pair_id", sa.String(), nullable=False),
        sa.Column("left_file_path", sa.String(), nullable=False),
        sa.Column("left_chunk_name", sa.String(), nullable=False),
        sa.Column("left_start_line", sa.Integer(), nullable=False),
        sa.Column("left_end_line", sa.Integer(), nullable=False),
        sa.Column("left_code", sa.Text(), nullable=False),
        sa.Column("right_file_path", sa.String(), nullable=False),
        sa.Column("right_chunk_name", sa.String(), nullable=False),
        sa.Column("right_start_line", sa.Integer(), nullable=False),
        sa.Column("right_end_line", sa.Integer(), nullable=False),
        sa.Column("right_code", sa.Text(), nullable=False),
        sa.UniqueConstraint("pair_id"),
        schema="api",
    )
    op.create_index("ix_api_calibration_pairs_pair_id", "calibration_pairs", ["pair_id"], schema="api")
    op.create_table(
        "calibration_labels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "pair_id", sa.Integer(), sa.ForeignKey("api.calibration_pairs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("api.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_duplicate", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("labeled_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("pair_id", "user_id", name="uq_calibration_labels_pair_user"),
        schema="api",
    )
    op.create_index("ix_api_calibration_labels_pair_id", "calibration_labels", ["pair_id"], schema="api")
    op.create_index("ix_api_calibration_labels_user_id", "calibration_labels", ["user_id"], schema="api")


def downgrade() -> None:
    op.drop_index("ix_api_calibration_labels_user_id", table_name="calibration_labels", schema="api")
    op.drop_index("ix_api_calibration_labels_pair_id", table_name="calibration_labels", schema="api")
    op.drop_table("calibration_labels", schema="api")
    op.drop_index("ix_api_calibration_pairs_pair_id", table_name="calibration_pairs", schema="api")
    op.drop_table("calibration_pairs", schema="api")
