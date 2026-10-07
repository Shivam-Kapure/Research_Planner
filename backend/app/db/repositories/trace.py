import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TraceEvent


class TraceRepository:
    """Read side of the trace. Writes go only through TraceRecorder (append-only)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def owned_run_exists(self, user_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        stmt = select(exists().where(TraceEvent.run_id == run_id, TraceEvent.user_id == user_id))
        return bool(await self._session.scalar(stmt))

    async def list_for_run(
        self, user_id: uuid.UUID, run_id: uuid.UUID, *, after_seq: int = 0, limit: int = 100
    ) -> list[TraceEvent]:
        result = await self._session.scalars(
            select(TraceEvent)
            .where(
                TraceEvent.run_id == run_id,
                TraceEvent.user_id == user_id,
                TraceEvent.seq > after_seq,
            )
            .order_by(TraceEvent.seq)
            .limit(limit)
        )
        return list(result)

    async def max_seq(self, run_id: uuid.UUID) -> int:
        value = await self._session.scalar(
            select(func.coalesce(func.max(TraceEvent.seq), 0)).where(TraceEvent.run_id == run_id)
        )
        return int(value or 0)
