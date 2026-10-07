import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """Owns the async engine and session factory for one application instance."""

    def __init__(self, url: str) -> None:
        # Small pool: Render Free runs one worker; Neon Free limits connections.
        self.engine: AsyncEngine = create_async_engine(
            url, pool_size=5, max_overflow=5, pool_pre_ping=True
        )
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def ping(self, timeout_s: float = 3.0) -> None:
        async with asyncio.timeout(timeout_s), self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()
