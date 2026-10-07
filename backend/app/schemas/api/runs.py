import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.contracts import FinalReview, ResearchRequest, SynthesisDecision

RunStatus = Literal[
    "queued", "running", "completed", "completed_with_limitations", "partial", "failed", "cancelled"
]
TERMINAL_STATUSES = ("completed", "completed_with_limitations", "partial", "failed", "cancelled")


class RunError(BaseModel):
    """Safe failure summary: an error code, a short message and the failing node. Never stack
    traces, provider responses, headers or credentials."""

    code: str
    message: str
    node: str | None = None


class RunProgress(BaseModel):
    iteration: int
    max_iterations: int
    llm_calls: int
    max_llm_calls: int
    tokens_used: int
    max_tokens: int


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    status: RunStatus
    iteration: int
    stop_reason: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class RunDetail(RunSummary):
    """Everything a client needs to poll a run (GET /api/runs/{id})."""

    request: ResearchRequest
    started_at: datetime | None
    error: RunError | None
    progress: RunProgress


class RunPage(BaseModel):
    items: list[RunSummary]
    total: int
    limit: int
    offset: int


class RunResult(BaseModel):
    """The outcome of a finished run. `review` is set for completed and
    completed_with_limitations runs; a partial run has the last synthesis instead."""

    run_id: uuid.UUID
    status: RunStatus
    stop_reason: str | None
    review: FinalReview | None
    synthesis: SynthesisDecision | None
    error: RunError | None


class AgentOutputOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent: str
    iteration: int
    schema_name: str
    schema_version: int
    created_at: datetime
    payload: dict[str, Any]
