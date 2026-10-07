import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class TraceEvent(Base):
    """Append-only execution trace (architecture §11). UPDATE and direct DELETE are rejected
    by a database trigger; rows only disappear through the owning user's cascade delete.

    `run_id` has no foreign key yet: the runs table arrives in Phase 7, which adds the
    constraint with a non-destructive ALTER TABLE. `user_id` scopes reads to the owner.
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
    run_id: Mapped[uuid.UUID]
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
