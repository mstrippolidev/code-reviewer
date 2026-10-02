from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import engine_from_config, pool

from api.config.settings import get_api_settings
from api.db.base import Base
from api.db.models.guest_session import GuestSession  # registers GuestSession on Base.metadata
from api.db.models.registered_repo import RegisteredRepo  # registers RegisteredRepo on Base.metadata
from api.db.models.user import User  # registers User on Base.metadata for autogenerate

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_api_settings()
config.set_main_option("sqlalchemy.url", settings.sync_database_url.render_as_string(hide_password=False))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        version_table_schema="api",
        include_schemas=True,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.execute(sa.schema.CreateSchema("api", if_not_exists=True))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="api",
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
