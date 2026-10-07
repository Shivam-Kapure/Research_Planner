import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PROVIDERS = ("groq", "gemini")
CREDENTIAL_STATUSES = ("unverified", "valid", "invalid")
TRACE_AGENTS = ("planner", "search", "analysis", "synthesis", "writer", "orchestrator")
TRACE_EVENT_TYPES = (
    "run_started",
    "agent_started",
    "agent_completed",
    "llm_call",
    "tool_call",
    "tool_result",
    "validation",
    "decision",
    "handoff",
    "retry",
    "replan",
    "fallback",
    "error",
    "run_completed",
)
TRACE_STATUSES = ("ok", "warning", "failed")


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Stored normalised (trimmed, lower-case) by the auth service.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created_at()


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # SHA-256 hex digest of the opaque cookie token; the raw token is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class ProviderCredential(Base):
    __tablename__ = "user_provider_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_provider_credentials_user_provider"),
        CheckConstraint(f"provider IN {PROVIDERS!r}", name="provider"),
        CheckConstraint(f"status IN {CREDENTIAL_STATUSES!r}", name="status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(16))
    # Fernet token of the API key; plaintext is never persisted.
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    key_hint: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(16), server_default="unverified")
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


RUN_STATUSES = (
    "queued",
    "running",
    "completed",
    "completed_with_limitations",
    "partial",
    "failed",
    "cancelled",
)
ACTIVE_RUN_STATUSES = ("queued", "running")


class Run(Base):
    """One research run (architecture §4). Holds lifecycle and progress only; the agents'
    structured outputs live in agent_outputs and the execution history in trace_events."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES!r}", name="status"),
        CheckConstraint("iteration >= 0", name="iteration_non_negative"),
        Index("ix_runs_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(String(1000))
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)  # the validated ResearchRequest
    status: Mapped[str] = mapped_column(String(32), server_default="queued")
    iteration: Mapped[int] = mapped_column(Integer, server_default="0")
    stop_reason: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    llm_calls: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_used: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentOutput(Base):
    """A validated agent contract (plan, search results, analysis, decision, replanning
    request, review), persisted as soon as the agent finishes. Trace events reference these
    via output_ref. No prompts, credentials or document full text are stored."""

    __tablename__ = "agent_outputs"
    __table_args__ = (
        CheckConstraint(f"agent IN {TRACE_AGENTS!r}", name="agent"),
        CheckConstraint("iteration >= 1", name="iteration_positive"),
        Index("ix_agent_outputs_run_id_created_at", "run_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    agent: Mapped[str] = mapped_column(String(16))
    iteration: Mapped[int] = mapped_column(Integer)
    schema_name: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()


class TraceEvent(Base):
    """Append-only execution trace (architecture §11). UPDATE and direct DELETE are rejected
    by a database trigger; rows only disappear through a cascade (run or user deletion).

    The run_id foreign key was added in Phase 7 as NOT VALID, so trace rows written before
    runs existed were kept; every new row is checked. `user_id` scopes reads to the owner.
    """

    __tablename__ = "trace_events"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_trace_events_run_seq"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint("iteration >= 0", name="iteration_non_negative"),
        CheckConstraint(f"agent IN {TRACE_AGENTS!r}", name="agent"),
        CheckConstraint(f"event_type IN {TRACE_EVENT_TYPES!r}", name="event_type"),
        CheckConstraint(f"status IN {TRACE_STATUSES!r}", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    iteration: Mapped[int] = mapped_column(Integer)
    agent: Mapped[str] = mapped_column(String(16))
    event_type: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(8))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trace_events.id", ondelete="CASCADE")
    )
    input_ref: Mapped[uuid.UUID | None]
    output_ref: Mapped[uuid.UUID | None]
    tool: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    llm: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    message: Mapped[str] = mapped_column(String(500))
