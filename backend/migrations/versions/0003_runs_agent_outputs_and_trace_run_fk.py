"""runs agent outputs and trace run fk

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08 01:54:11.890557
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.String(length=1000), nullable=False),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("iteration", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column(
            "error", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("llm_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'completed_with_limitations', 'partial', 'failed', 'cancelled')",
            name=op.f("ck_runs_status"),
        ),
        sa.CheckConstraint("iteration >= 0", name=op.f("ck_runs_iteration_non_negative")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_runs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    op.create_index("ix_runs_user_id_created_at", "runs", ["user_id", "created_at"], unique=False)
    op.create_table(
        "agent_outputs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.String(length=16), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("schema_name", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "agent IN ('planner', 'search', 'analysis', 'synthesis', 'writer', 'orchestrator')",
            name=op.f("ck_agent_outputs_agent"),
        ),
        sa.CheckConstraint("iteration >= 1", name=op.f("ck_agent_outputs_iteration_positive")),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_agent_outputs_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_outputs")),
    )
    op.create_index(
        "ix_agent_outputs_run_id_created_at",
        "agent_outputs",
        ["run_id", "created_at"],
        unique=False,
    )
    # Non-destructive: NOT VALID enforces the FK for every new trace row without checking (or
    # deleting) trace rows written before runs existed. Append-only semantics are unchanged.
    op.execute(
        "ALTER TABLE trace_events ADD CONSTRAINT fk_trace_events_run_id_runs "
        "FOREIGN KEY (run_id) REFERENCES runs (id) ON DELETE CASCADE NOT VALID"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_trace_events_run_id_runs"), "trace_events", type_="foreignkey")
    op.drop_index("ix_agent_outputs_run_id_created_at", table_name="agent_outputs")
    op.drop_table("agent_outputs")
    op.drop_index("ix_runs_user_id_created_at", table_name="runs")
    op.drop_table("runs")
