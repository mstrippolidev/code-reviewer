"""create review_incidents and finding_feedback tables

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

FEEDBACK_VERDICT = sa.Enum("up", "down", name="feedback_verdict", schema="api")
FEEDBACK_REASON = sa.Enum(
    "not_true", "wrong_lines", "not_actionable", "wrong_severity", "other", name="feedback_reason", schema="api"
)


def upgrade() -> None:
    op.create_table(
        "review_incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "review_job_id", sa.Integer(), sa.ForeignKey("api.review_jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("code_key", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("line_position", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("advice", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "review_job_id", "file_path", "code_key", "content_digest", name="uq_review_incidents_content"
        ),
        schema="api",
    )
    op.create_index("ix_api_review_incidents_review_job_id", "review_incidents", ["review_job_id"], schema="api")
    op.create_table(
        "finding_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "incident_id", sa.Integer(), sa.ForeignKey("api.review_incidents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("rater_key", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("api.users.id", ondelete="CASCADE"), nullable=True),
        sa.Column(
            "guest_session_id",
            sa.Integer(),
            sa.ForeignKey("api.guest_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("verdict", FEEDBACK_VERDICT, nullable=False),
        sa.Column("reason", FEEDBACK_REASON, nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("incident_id", "rater_key", name="uq_finding_feedback_incident_rater"),
        schema="api",
    )
    op.create_index("ix_api_finding_feedback_incident_id", "finding_feedback", ["incident_id"], schema="api")
    op.create_index("ix_api_finding_feedback_user_id", "finding_feedback", ["user_id"], schema="api")
    op.create_index("ix_api_finding_feedback_guest_session_id", "finding_feedback", ["guest_session_id"], schema="api")


def downgrade() -> None:
    op.drop_index("ix_api_finding_feedback_guest_session_id", table_name="finding_feedback", schema="api")
    op.drop_index("ix_api_finding_feedback_user_id", table_name="finding_feedback", schema="api")
    op.drop_index("ix_api_finding_feedback_incident_id", table_name="finding_feedback", schema="api")
    op.drop_table("finding_feedback", schema="api")
    FEEDBACK_REASON.drop(op.get_bind(), checkfirst=True)
    FEEDBACK_VERDICT.drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_api_review_incidents_review_job_id", table_name="review_incidents", schema="api")
    op.drop_table("review_incidents", schema="api")
