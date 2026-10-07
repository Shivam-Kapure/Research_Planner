import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

TraceAgent = Literal["planner", "search", "analysis", "synthesis", "writer", "orchestrator"]
EventType = Literal[
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
]
EventStatus = Literal["ok", "warning", "failed"]

# Field limits; the sanitizer truncates to the same limits before validation.
MESSAGE_LIMIT = 500
TEXT_LIMIT = 1000
RAW_EXCERPT_LIMIT = 2000


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolInfo(_Payload):
    name: str = Field(min_length=1, max_length=100)
    args: dict[str, Any] = Field(default_factory=dict)
    result_summary: str | None = Field(default=None, max_length=TEXT_LIMIT)
    duration_ms: int | None = Field(default=None, ge=0)


class DecisionInfo(_Payload):
    route: str = Field(min_length=1, max_length=100)  # verdict or route taken
    rationale: str = Field(min_length=1, max_length=TEXT_LIMIT)
    from_agent: TraceAgent | None = None
    to_agent: TraceAgent | None = None


class ValidationInfo(_Payload):
    schema_name: str = Field(min_length=1, max_length=100)
    passed: bool
    errors: list[str] = Field(default_factory=list, max_length=50)
    dropped_items: int = Field(default=0, ge=0)
    override: str | None = Field(default=None, max_length=TEXT_LIMIT)
    raw_excerpt: str | None = Field(default=None, max_length=RAW_EXCERPT_LIMIT)


class LLMInfo(_Payload):
    """Call metadata only: prompt text is never stored in llm_call events."""

    provider: Literal["groq", "gemini"]
    model: str = Field(min_length=1, max_length=128)
    attempt: int = Field(ge=1)
    kind: Literal["initial", "transient_retry", "repair"]
    outcome: Literal["ok", "error", "invalid_output"]
    tokens_in: int | None = Field(default=None, ge=0)
    tokens_out: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=64)


class ErrorInfo(_Payload):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=TEXT_LIMIT)
    retryable: bool
    attempt: int | None = Field(default=None, ge=1)


_REQUIRED_PAYLOAD: dict[str, str] = {
    "tool_call": "tool",
    "tool_result": "tool",
    "llm_call": "llm",
    "validation": "validation",
    "decision": "decision",
    "handoff": "decision",
    "replan": "decision",
    "fallback": "decision",
    "error": "error",
}


class TraceEventIn(_Payload):
    iteration: int = Field(default=0, ge=0)
    agent: TraceAgent
    event_type: EventType
    status: EventStatus = "ok"
    message: str = Field(min_length=1, max_length=MESSAGE_LIMIT)
    parent_id: uuid.UUID | None = None
    input_ref: uuid.UUID | None = None
    output_ref: uuid.UUID | None = None
    tool: ToolInfo | None = None
    decision: DecisionInfo | None = None
    validation: ValidationInfo | None = None
    llm: LLMInfo | None = None
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def _payload_matches_type(self) -> Self:
        required = _REQUIRED_PAYLOAD.get(self.event_type)
        if required and getattr(self, required) is None:
            raise ValueError(f"{self.event_type} events require a {required!r} payload")
        if self.event_type == "error" and self.status == "ok":
            raise ValueError("error events cannot have status 'ok'")
        return self


class TraceEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    seq: int
    ts: datetime
    iteration: int
    agent: str
    event_type: str
    status: str
    message: str
    parent_id: uuid.UUID | None
    input_ref: uuid.UUID | None
    output_ref: uuid.UUID | None
    tool: dict[str, Any] | None
    decision: dict[str, Any] | None
    validation: dict[str, Any] | None
    llm: dict[str, Any] | None
    error: dict[str, Any] | None
