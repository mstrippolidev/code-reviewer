from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


class DatabaseEngine:
    """Owns the async engine and session factory for api/'s own Postgres tables."""

    def __init__(self, database_url: URL, *, echo: bool = False) -> None:
        self._engine: AsyncEngine = create_async_engine(database_url, echo=echo, pool_pre_ping=True)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    def new_session(self) -> AsyncSession:
        return self._session_factory()

    async def dispose(self) -> None:
        await self._engine.dispose()
