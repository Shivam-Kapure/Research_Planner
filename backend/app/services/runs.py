"""Run execution: POST /api/runs → runs row → in-process asyncio task → Phase 6 graph.

Architecture §2 / Render Free: one process, bounded concurrency (an asyncio semaphore), no
queue or worker infrastructure. Queued and running runs live in this process only; after a
restart the startup sweep marks them failed ("interrupted"). Execution is not durable.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.credentials import CredentialRepository
from app.db.repositories.runs import RunRepository
from app.llm.gateway import LLMGateway
from app.orchestration.runner import run_research
from app.orchestration.runtime import LiteratureSearch, ResearchLimits, ResearchRuntime, RunBudget
from app.orchestration.state import ResearchState
from app.schemas.contracts import Contract, ResearchRequest
from app.schemas.trace import TraceAgent
from app.services.trace_recorder import TraceRecorder
from app.tools.documents.pdf import SafePdfFetcher

logger = logging.getLogger(__name__)

GatewayFactory = Callable[[AsyncSession, uuid.UUID], Awaitable[LLMGateway]]


class DbRunSink:
    """Persists one run's agent outputs and progress as they happen (own short transactions)."""

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], run_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        self._sessionmaker = sessionmaker
        self._run_id = run_id
        self._user_id = user_id

    async def save_output(self, agent: TraceAgent, iteration: int, output: Contract) -> uuid.UUID:
        async with self._sessionmaker() as session, session.begin():
            return await RunRepository(session).add_output(
                self._run_id,
                agent=agent,
                iteration=iteration,
                schema_name=output.schema_name,
                schema_version=output.schema_version,
                payload=output.model_dump(mode="json"),
            )

    async def progress(self, iteration: int, budget: RunBudget) -> None:
        async with self._sessionmaker() as session, session.begin():
            await RunRepository(session).update(
                self._run_id, iteration=iteration, llm_calls=budget.calls, tokens_used=budget.tokens
            )

    async def credential_rejected(self, provider: str) -> None:
        async with self._sessionmaker() as session, session.begin():
            await CredentialRepository(session).set_status(self._user_id, provider, "invalid")
        logger.warning("run %s: %s rejected the stored key; marked invalid", self._run_id, provider)


class RunExecutor:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        gateway_factory: GatewayFactory,
        literature: LiteratureSearch,
        fetcher: SafePdfFetcher,
        max_concurrent: int = 1,
        limits: ResearchLimits | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._gateway_factory = gateway_factory
        self._literature = literature
        self._fetcher = fetcher
        self._limits = limits or ResearchLimits()
        self._slots = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    @property
    def limits(self) -> ResearchLimits:
        return self._limits

    async def submit(self, run_id: uuid.UUID, user_id: uuid.UUID, request: ResearchRequest) -> None:
        """Start the run in the background (the HTTP request returns immediately)."""
        task = asyncio.create_task(self._execute(run_id, user_id, request), name=f"run-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))

    def is_active(self, run_id: uuid.UUID) -> bool:
        return run_id in self._tasks

    def cancel(self, run_id: uuid.UUID) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def sweep_interrupted(self) -> int:
        async with self._sessionmaker() as session, session.begin():
            return await RunRepository(session).mark_interrupted()

    async def _execute(
        self, run_id: uuid.UUID, user_id: uuid.UUID, request: ResearchRequest
    ) -> None:
        recorder: TraceRecorder | None = None
        try:
            async with self._slots:  # bounded concurrency: extra runs stay 'queued' here
                await self._update(run_id, status="running", started_at=datetime.now(UTC))
                async with self._sessionmaker() as session:
                    gateway = await self._gateway_factory(session, user_id)
                recorder = await TraceRecorder.open(
                    self._sessionmaker, run_id=run_id, user_id=user_id
                )
                runtime = ResearchRuntime(
                    gateway=gateway,
                    literature=self._literature,
                    fetcher=self._fetcher,
                    recorder=recorder,
                    limits=self._limits,
                    sink=DbRunSink(self._sessionmaker, run_id, user_id),
                )
                state = await run_research(runtime, request)
                await self._finish(run_id, state, runtime.budget)
        except asyncio.CancelledError:
            await self._update(
                run_id,
                status="cancelled",
                completed_at=datetime.now(UTC),
                error={"code": "cancelled", "message": "Run cancelled.", "node": "run"},
            )
            if recorder is not None:
                await recorder.record(
                    {
                        "agent": "orchestrator",
                        "event_type": "run_completed",
                        "status": "failed",
                        "message": "run cancelled",
                    }
                )
            raise
        except Exception as exc:  # noqa: BLE001 - never let a run crash silently
            logger.error("run %s crashed: %s", run_id, type(exc).__name__)
            await self._update(
                run_id,
                status="failed",
                completed_at=datetime.now(UTC),
                error={
                    "code": "internal_error",
                    "message": "The run failed unexpectedly.",
                    "node": "run",
                },
            )

    async def _finish(self, run_id: uuid.UUID, state: ResearchState, budget: RunBudget) -> None:
        fatal = next((e for e in reversed(state.get("errors", [])) if e.fatal), None)
        values: dict[str, Any] = {
            "status": state.get("status", "failed"),
            "iteration": state.get("iteration", 1),
            "stop_reason": state.get("stop_reason"),
            "llm_calls": budget.calls,
            "tokens_used": budget.tokens,
            "completed_at": datetime.now(UTC),
            "error": (
                {"code": fatal.code, "message": fatal.message[:300], "node": fatal.node}
                if fatal
                else None
            ),
        }
        await self._update(run_id, **values)

    async def _update(self, run_id: uuid.UUID, **values: Any) -> None:
        async with self._sessionmaker() as session, session.begin():
            await RunRepository(session).update(run_id, **values)
