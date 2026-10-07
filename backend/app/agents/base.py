"""Shared plumbing for the five agents: LLM calls through the Phase 4 gateway with provider
fallback, budget accounting and tracing. Each agent keeps its own responsibility, prompt,
input and output contract; nothing here decides research content."""

import json
import uuid
from typing import Any, ClassVar

from pydantic import BaseModel

from app.llm.errors import LLMError, NoProviderConfigured, ProviderAuthError
from app.llm.gateway import AttemptRecord
from app.llm.types import Message
from app.orchestration.runtime import ResearchRuntime
from app.schemas.contracts import AgentName
from app.schemas.trace import TraceAgent

MAX_CANDIDATES_PER_CALL = 3  # primary model + at most two fallbacks


def as_json(value: Any) -> str:
    """Compact JSON for prompts (Pydantic models, lists of models, dicts)."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, list | tuple):
        value = [v.model_dump(mode="json") if isinstance(v, BaseModel) else v for v in value]
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class Agent:
    node: ClassVar[str]  # LangGraph node name
    trace_agent: ClassVar[TraceAgent]  # agent value recorded in trace_events
    role: ClassVar[AgentName]  # provider/model preference role
    writer_budget: ClassVar[bool] = False

    def __init__(self, runtime: ResearchRuntime) -> None:
        self.rt = runtime

    async def llm[T: BaseModel](
        self,
        schema: type[T],
        messages: list[Message],
        *,
        iteration: int,
        parent_id: uuid.UUID | None,
        max_output_tokens: int,
    ) -> T:
        """Structured LLM call. Tries the role's preferred provider/model, then falls back to
        the next candidate (traced as a 'fallback' decision) if that one fails."""
        candidates = self.rt.gateway.candidates(self.role)[:MAX_CANDIDATES_PER_CALL]
        for index, choice in enumerate(candidates):
            self.rt.budget.check(writer=self.writer_budget)
            try:
                result = await self.rt.gateway.generate_structured(
                    schema, messages, choice=choice, max_output_tokens=max_output_tokens
                )
            except NoProviderConfigured:
                raise
            except LLMError as exc:
                await self._trace_attempts(exc.attempts, iteration, parent_id)
                if isinstance(exc, ProviderAuthError) and self.rt.sink:
                    await self.rt.sink.credential_rejected(choice.provider)
                if index == len(candidates) - 1:
                    raise
                following = candidates[index + 1]
                await self.rt.recorder.decision(
                    self.trace_agent,
                    iteration=iteration,
                    route=f"fallback to {following.provider}/{following.model}",
                    rationale=f"{choice.provider}/{choice.model} failed with {exc.code}",
                    event_type="fallback",
                    parent_id=parent_id,
                )
                continue
            await self._trace_attempts(result.attempts, iteration, parent_id)
            return result.value
        raise AssertionError("unreachable")  # pragma: no cover

    async def _trace_attempts(
        self, attempts: tuple[object, ...], iteration: int, parent_id: uuid.UUID | None
    ) -> None:
        records = tuple(a for a in attempts if isinstance(a, AttemptRecord))
        self.rt.budget.record(records)
        for attempt in records:
            await self.rt.recorder.llm_call(
                self.trace_agent, iteration=iteration, attempt=attempt, parent_id=parent_id
            )
