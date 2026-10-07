"""append-only trace events

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08 00:35:11.970723
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Append-only: UPDATE is always rejected; DELETE only when it cascades from a deleted user
# (pg_trigger_depth() >= 2 inside a foreign-key cascade), never as a direct statement.
APPEND_ONLY_FUNCTION = """
CREATE FUNCTION trace_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'trace_events is append-only: UPDATE is not allowed';
    END IF;
    IF pg_trigger_depth() < 2 THEN
        RAISE EXCEPTION 'trace_events is append-only: direct DELETE is not allowed';
    END IF;
    RETURN OLD;
END;
$$
"""
APPEND_ONLY_TRIGGER = """
CREATE TRIGGER trace_events_append_only
BEFORE UPDATE OR DELETE ON trace_events
FOR EACH ROW EXECUTE FUNCTION trace_events_append_only()
"""

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trace_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("agent", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("input_ref", sa.Uuid(), nullable=True),
        sa.Column("output_ref", sa.Uuid(), nullable=True),
        sa.Column(
            "tool", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "decision", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "validation", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("llm", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
        sa.Column(
            "error", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.CheckConstraint(
            "agent IN ('planner', 'search', 'analysis', 'synthesis', 'writer', 'orchestrator')",
            name=op.f("ck_trace_events_agent"),
        ),
        sa.CheckConstraint(
            "event_type IN ('run_started', 'agent_started', 'agent_completed', 'llm_call', 'tool_call', 'tool_result', 'validation', 'decision', 'handoff', 'retry', 'replan', 'fallback', 'error', 'run_completed')",
            name=op.f("ck_trace_events_event_type"),
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'warning', 'failed')", name=op.f("ck_trace_events_status")
        ),
        sa.CheckConstraint("iteration >= 0", name=op.f("ck_trace_events_iteration_non_negative")),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_trace_events_seq_positive")),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["trace_events.id"],
            name=op.f("fk_trace_events_parent_id_trace_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_trace_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trace_events")),
        sa.UniqueConstraint("run_id", "seq", name="uq_trace_events_run_seq"),
    )
    op.create_index(op.f("ix_trace_events_user_id"), "trace_events", ["user_id"], unique=False)
    op.execute(APPEND_ONLY_FUNCTION)
    op.execute(APPEND_ONLY_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trace_events_append_only ON trace_events")
    op.execute("DROP FUNCTION IF EXISTS trace_events_append_only()")
    op.drop_index(op.f("ix_trace_events_user_id"), table_name="trace_events")
    op.drop_table("trace_events")
