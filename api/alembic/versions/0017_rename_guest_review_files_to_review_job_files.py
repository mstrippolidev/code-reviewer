"""rename guest_review_files to review_job_files

The table keeps the raw source of any review job whose files are not in the index (a guest's, a user's repoless
review, a pull request's), so the guest name was misleading.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-31

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

RENAMED_CONSTRAINTS = [
    ("guest_review_files_pkey", "review_job_files_pkey"),
    ("guest_review_files_review_job_id_fkey", "review_job_files_review_job_id_fkey"),
    ("guest_review_files_review_job_id_file_path_key", "review_job_files_review_job_id_file_path_key"),
]


def upgrade() -> None:
    op.rename_table("guest_review_files", "review_job_files", schema="api")
    for old_name, new_name in RENAMED_CONSTRAINTS:
        op.execute(f"ALTER TABLE api.review_job_files RENAME CONSTRAINT {old_name} TO {new_name}")
    op.execute(
        "ALTER INDEX api.ix_api_guest_review_files_review_job_id RENAME TO ix_api_review_job_files_review_job_id"
    )
    op.execute("ALTER SEQUENCE api.guest_review_files_id_seq RENAME TO review_job_files_id_seq")


def downgrade() -> None:
    op.execute("ALTER SEQUENCE api.review_job_files_id_seq RENAME TO guest_review_files_id_seq")
    op.execute(
        "ALTER INDEX api.ix_api_review_job_files_review_job_id RENAME TO ix_api_guest_review_files_review_job_id"
    )
    for old_name, new_name in RENAMED_CONSTRAINTS:
        op.execute(f"ALTER TABLE api.review_job_files RENAME CONSTRAINT {new_name} TO {old_name}")
    op.rename_table("review_job_files", "guest_review_files", schema="api")
