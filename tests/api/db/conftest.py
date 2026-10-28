from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from api.config.settings import get_api_settings


@pytest_asyncio.fixture
async def async_session() -> AsyncIterator[AsyncSession]:
    """An AsyncSession inside a transaction that is rolled back at the end, so nothing is persisted."""
    engine = create_async_engine(get_api_settings().async_database_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        test_session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)

        yield test_session

        await test_session.close()
        await transaction.rollback()
    await engine.dispose()
