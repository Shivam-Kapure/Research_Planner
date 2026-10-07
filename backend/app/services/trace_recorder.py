import asyncio
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import TraceEvent
from app.db.repositories.trace import TraceRepository
from app.llm.gateway import AttemptRecord
from app.schemas.trace import EventStatus, TraceAgent, TraceEventIn
from app.services.trace_sanitize import sanitize

_LLM_OUTCOME_STATUS: dict[str, EventStatus] = {
    "ok": "ok",
    "invalid_output": "warning",
    "error": "failed",
}


@dataclass(frozen=True)
class RecordedEvent:
    id: uuid.UUID
    seq: int
    ts: datetime


class TraceRecorder:
    """Appends events for one run. Each event is committed in its own short transaction, so
    the trace survives even if the agent step that produced it later fails.

    Sequence numbers are assigned under a lock, so they are gap-free and deterministic per
    run; the (run_id, seq) unique constraint guards against a second writer. There is no
    update or delete API, and the database rejects both.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        last_seq: int = 0,
    ) -> None:
        self._sessionmaker = sessionmaker
        self.run_id = run_id
        self.user_id = user_id
        self._seq = last_seq
        self._lock = asyncio.Lock()

    @classmethod
    async def open(
        cls,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> "TraceRecorder":
        """Continue an existing run's sequence (or start at 1)."""
        async with sessionmaker() as session:
            last = await TraceRepository(session).max_seq(run_id)
        return cls(sessionmaker, run_id=run_id, user_id=user_id, last_seq=last)

    async def record(self, event: TraceEventIn | Mapping[str, Any]) -> RecordedEvent:
        """Sanitize, validate and append one event. The only write path to trace_events."""
        raw = event.model_dump() if isinstance(event, TraceEventIn) else dict(event)
        clean = TraceEventIn.model_validate(sanitize(raw))
        async with self._lock:
            seq = self._seq + 1
            row = TraceEvent(
                id=uuid.uuid4(),
                run_id=self.run_id,
                user_id=self.user_id,
                seq=seq,
                ts=datetime.now(UTC),
                **clean.model_dump(mode="json", exclude={"parent_id", "input_ref", "output_ref"}),
                parent_id=clean.parent_id,
                input_ref=clean.input_ref,
                output_ref=clean.output_ref,
            )
            async with self._sessionmaker() as session, session.begin():
                session.add(row)
            self._seq = seq
            return RecordedEvent(row.id, row.seq, row.ts)

    # ---- typed helpers for agents (Phase 6) ----

    async def agent_started(
        self, agent: TraceAgent, *, iteration: int, message: str, input_ref: uuid.UUID | None = None
    ) -> RecordedEvent:
        return await self.record(
            {
                "agent": agent,
                "event_type": "agent_started",
                "iteration": iteration,
                "message": message,
                "input_ref": input_ref,
            }
        )

    async def agent_completed(
        self,
        agent: TraceAgent,
        *,
        iteration: int,
        message: str,
        parent_id: uuid.UUID | None = None,
        output_ref: uuid.UUID | None = None,
        status: EventStatus = "ok",
    ) -> RecordedEvent:
        return await self.record(
            {
                "agent": agent,
                "event_type": "agent_completed",
                "iteration": iteration,
                "message": message,
                "parent_id": parent_id,
                "output_ref": output_ref,
                "status": status,
            }
        )

    async def tool_call(
        self,
        agent: TraceAgent,
        *,
        iteration: int,
        name: str,
        args: Mapping[str, Any],
        result_summary: str | None = None,
        duration_ms: int | None = None,
        status: EventStatus = "ok",
        parent_id: uuid.UUID | None = None,
    ) -> RecordedEvent:
        return await self.record(
            {
                "agent": agent,
                "event_type": "tool_call",
                "iteration": iteration,
                "status": status,
                "parent_id": parent_id,
                "message": f"{agent} called {name}",
                "tool": {
                    "name": name,
                    "args": dict(args),
                    "result_summary": result_summary,
                    "duration_ms": duration_ms,
                },
            }
        )

    async def llm_call(
        self,
        agent: TraceAgent,
        *,
        iteration: int,
        attempt: AttemptRecord,
        parent_id: uuid.UUID | None = None,
    ) -> RecordedEvent:
        status = _LLM_OUTCOME_STATUS[attempt.outcome]
        return await self.record(
            {
                "agent": agent,
                "event_type": "llm_call",
                "iteration": iteration,
                "status": status,
                "parent_id": parent_id,
                "message": f"{attempt.provider}/{attempt.model} {attempt.kind} → {attempt.outcome}",
                "llm": {
                    "provider": attempt.provider,
                    "model": attempt.model,
                    "attempt": attempt.attempt,
                    "kind": attempt.kind,
                    "outcome": attempt.outcome,
                    "tokens_in": attempt.input_tokens,
                    "tokens_out": attempt.output_tokens,
                    "latency_ms": attempt.latency_ms,
                    "error_code": attempt.error_code,
                },
            }
        )

    async def decision(
        self,
        agent: TraceAgent,
        *,
        iteration: int,
        route: str,
        rationale: str,
        to_agent: TraceAgent | None = None,
        event_type: Literal["decision", "handoff", "replan", "fallback"] = "decision",
        input_ref: uuid.UUID | None = None,
        output_ref: uuid.UUID | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> RecordedEvent:
        return await self.record(
            {
                "agent": agent,
                "event_type": event_type,
                "iteration": iteration,
                "parent_id": parent_id,
                "input_ref": input_ref,
                "output_ref": output_ref,
                "message": f"{agent}: {route}" + (f" → {to_agent}" if to_agent else ""),
                "decision": {
                    "route": route,
                    "rationale": rationale,
                    "from_agent": agent,
                    "to_agent": to_agent,
                },
            }
        )

    async def validation(
        self,
        agent: TraceAgent,
        *,
        iteration: int,
        schema_name: str,
        passed: bool,
        errors: Iterable[str] = (),
        dropped_items: int = 0,
        override: str | None = None,
        raw_excerpt: str | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> RecordedEvent:
        return await self.record(
            {
                "agent": agent,
                "event_type": "validation",
                "iteration": iteration,
                "status": "ok" if passed and not override else "warning",
                "parent_id": parent_id,
                "message": f"{schema_name} validation {'passed' if passed else 'failed'}",
                "validation": {
                    "schema_name": schema_name,
                    "passed": passed,
                    "errors": list(errors),
                    "dropped_items": dropped_items,
                    "override": override,
                    "raw_excerpt": raw_excerpt,
                },
            }
        )

    async def error(
        self,
        agent: TraceAgent,
        *,
        iteration: int,
        code: str,
        message: str,
        retryable: bool,
        attempt: int | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> RecordedEvent:
        return await self.record(
            {
                "agent": agent,
                "event_type": "error",
                "iteration": iteration,
                "status": "failed",
                "parent_id": parent_id,
                "message": f"{agent} error: {code}",
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                    "attempt": attempt,
                },
            }
        )
