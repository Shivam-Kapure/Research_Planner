import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ACTIVE_RUN_STATUSES, AgentOutput, Run


class RunRepository:
    """Runs and their agent outputs. Every read is scoped by user_id: another user's run is
    indistinguishable from a missing one."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: uuid.UUID, question: str, request: dict[str, Any]) -> Run:
        run = Run(user_id=user_id, question=question, request=request, status="queued")
        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def get_owned(self, user_id: uuid.UUID, run_id: uuid.UUID) -> Run | None:
        return await self._session.scalar(
            select(Run).where(Run.id == run_id, Run.user_id == user_id)
        )

    async def list_owned(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[Run], int]:
        total = await self._session.scalar(
            select(func.count()).select_from(Run).where(Run.user_id == user_id)
        )
        rows = await self._session.scalars(
            select(Run)
            .where(Run.user_id == user_id)
            .order_by(Run.created_at.desc(), Run.id)
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def has_active(self, user_id: uuid.UUID) -> bool:
        count = await self._session.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.user_id == user_id, Run.status.in_(ACTIVE_RUN_STATUSES))
        )
        return bool(count)

    async def update(self, run_id: uuid.UUID, **values: Any) -> None:
        await self._session.execute(update(Run).where(Run.id == run_id).values(**values))

    async def mark_interrupted(self) -> int:
        """Startup sweep: runs left queued/running by a previous process cannot resume."""
        result = await self._session.execute(
            update(Run)
            .where(Run.status.in_(ACTIVE_RUN_STATUSES))
            .values(
                status="failed",
                completed_at=datetime.now(UTC),
                error={
                    "code": "interrupted",
                    "message": "The server restarted before this run finished.",
                    "node": "run",
                },
            )
            .returning(Run.id)
        )
        return len(result.all())

    async def add_output(
        self,
        run_id: uuid.UUID,
        *,
        agent: str,
        iteration: int,
        schema_name: str,
        schema_version: int,
        payload: dict[str, Any],
    ) -> uuid.UUID:
        output = AgentOutput(
            id=uuid.uuid4(),
            run_id=run_id,
            agent=agent,
            iteration=iteration,
            schema_name=schema_name,
            schema_version=schema_version,
            payload=payload,
        )
        self._session.add(output)
        await self._session.flush()
        return output.id

    async def outputs(
        self, run_id: uuid.UUID, *, agent: str | None = None, iteration: int | None = None
    ) -> list[AgentOutput]:
        stmt = select(AgentOutput).where(AgentOutput.run_id == run_id)
        if agent:
            stmt = stmt.where(AgentOutput.agent == agent)
        if iteration:
            stmt = stmt.where(AgentOutput.iteration == iteration)
        return list(
            await self._session.scalars(stmt.order_by(AgentOutput.created_at, AgentOutput.id))
        )

    async def latest_output(self, run_id: uuid.UUID, schema_name: str) -> AgentOutput | None:
        return await self._session.scalar(
            select(AgentOutput)
            .where(AgentOutput.run_id == run_id, AgentOutput.schema_name == schema_name)
            .order_by(AgentOutput.created_at.desc())
            .limit(1)
        )
