"""add the OAuth authorization server tables: clients, consents and tokens

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-27

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

CLIENT_FK = "api.oauth_clients.client_id"
USER_FK = "api.users.id"


def upgrade() -> None:
    _create_clients()
    _create_consents()
    _create_tokens()


def downgrade() -> None:
    op.drop_table("oauth_tokens", schema="api")
    op.drop_table("oauth_consents", schema="api")
    op.drop_table("oauth_clients", schema="api")


def _create_clients() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(64), primary_key=True),
        sa.Column("client_name", sa.String(200), nullable=False),
        sa.Column("redirect_uris", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="api",
    )


def _create_consents() -> None:
    op.create_table(
        "oauth_consents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey(USER_FK, ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(64), sa.ForeignKey(CLIENT_FK, ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "client_id"),
        schema="api",
    )
    op.create_index("ix_api_oauth_consents_client_id", "oauth_consents", ["client_id"], schema="api")


def _create_tokens() -> None:
    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("access_token_hash", sa.String(64), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(), nullable=False),
        sa.Column("refresh_used_at", sa.DateTime(), nullable=True),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("authorized_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey(USER_FK, ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(64), sa.ForeignKey(CLIENT_FK, ondelete="CASCADE"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="api",
    )
    op.create_index(
        "ix_api_oauth_tokens_access_token_hash", "oauth_tokens", ["access_token_hash"], unique=True, schema="api"
    )
    op.create_index(
        "ix_api_oauth_tokens_refresh_token_hash", "oauth_tokens", ["refresh_token_hash"], unique=True, schema="api"
    )
    op.create_index("ix_api_oauth_tokens_family_id", "oauth_tokens", ["family_id"], schema="api")
    op.create_index("ix_api_oauth_tokens_user_id", "oauth_tokens", ["user_id"], schema="api")
