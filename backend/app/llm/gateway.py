import asyncio
import dataclasses
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.llm.errors import LLMError, MalformedOutput, NoProviderConfigured, StructuredOutputError
from app.llm.rate_limit import RateLimiter
from app.llm.retry import RetryPolicy
from app.llm.structured import OutputParseError, json_instruction, parse_output, schema_name
from app.llm.types import PROVIDERS, LLMProvider, LLMRequest, LLMResponse, Message, ProviderName
from app.schemas.contracts import AgentName

# Architecture §6: Groq (fast) for high-volume roles, Gemini (long context) for synthesis and
# writing. A role falls back to whichever provider the user has configured.
ROLE_PROVIDER_PREFERENCE: dict[AgentName, tuple[ProviderName, ...]] = {
    "planner": ("groq", "gemini"),
    "search": ("groq", "gemini"),
    "analysis": ("groq", "gemini"),
    "synthesis": ("gemini", "groq"),
    "writer": ("gemini", "groq"),
}

AttemptKind = Literal["initial", "transient_retry", "repair"]


@dataclass(frozen=True)
class ModelChoice:
    provider: ProviderName
    model: str


@dataclass(frozen=True)
class AttemptRecord:
    """One provider call. Metadata only: never prompt text or credentials."""

    provider: ProviderName
    model: str
    attempt: int
    kind: AttemptKind
    outcome: Literal["ok", "error", "invalid_output"]
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    value: T
    response: LLMResponse
    attempts: tuple[AttemptRecord, ...]


class LLMGateway:
    """The single entry point agents will use for LLM calls (Phase 6)."""

    def __init__(
        self,
        providers: Mapping[ProviderName, LLMProvider],
        models: Mapping[ProviderName, Sequence[str]],
        *,
        limiters: Mapping[ProviderName, RateLimiter] | None = None,
        policy: RetryPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._providers = dict(providers)
        self._models = {name: list(models.get(name, ())) for name in PROVIDERS}
        self._limiters = dict(limiters or {})
        self._policy = policy or RetryPolicy()
        self._sleep = sleep

    @property
    def available(self) -> tuple[ProviderName, ...]:
        """Providers with a stored key and at least one configured model."""
        return tuple(p for p in PROVIDERS if p in self._providers and self._models[p])

    def candidates(self, role: AgentName | None = None) -> list[ModelChoice]:
        """Ordered (provider, model) options for a role; later entries are fallbacks."""
        order = ROLE_PROVIDER_PREFERENCE[role] if role else PROVIDERS
        choices = [ModelChoice(p, m) for p in order if p in self.available for m in self._models[p]]
        if choices:
            return choices
        if not self._providers:
            raise NoProviderConfigured(
                None, "No LLM provider key is configured. Add a Groq or Gemini API key first."
            )
        raise NoProviderConfigured(
            None,
            "No model is configured for the stored provider key(s): set GROQ_MODELS and/or "
            "GEMINI_MODELS.",
        )

    async def generate(
        self, request: LLMRequest, provider: ProviderName
    ) -> tuple[LLMResponse, tuple[AttemptRecord, ...]]:
        attempts: list[AttemptRecord] = []
        response = await self._call(provider, request, attempts, "initial")
        return response, tuple(attempts)

    async def generate_structured[T: BaseModel](
        self,
        schema: type[T],
        messages: Sequence[Message],
        *,
        role: AgentName | None = None,
        choice: ModelChoice | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
    ) -> StructuredResult[T]:
        """Call the model and return a validated instance of `schema`.

        Bounded: one repair round (feeding back validation errors), each provider call with
        at most `max_transient_retries` retries, so at most 6 provider calls in total.
        """
        choice = choice or self.candidates(role)[0]
        attempts: list[AttemptRecord] = []
        try:
            return await self._structured(
                schema, messages, choice, attempts, temperature, max_output_tokens
            )
        except LLMError as exc:
            exc.attempts = tuple(attempts)
            raise

    async def _structured[T: BaseModel](
        self,
        schema: type[T],
        messages: Sequence[Message],
        choice: ModelChoice,
        attempts: list[AttemptRecord],
        temperature: float,
        max_output_tokens: int,
    ) -> StructuredResult[T]:
        conversation = [Message("system", json_instruction(schema)), *messages]
        for repair in range(self._policy.max_repair_retries + 1):
            request = LLMRequest(
                tuple(conversation),
                choice.model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                json_mode=True,
            )
            raw = ""
            try:
                response = await self._call(
                    choice.provider, request, attempts, "repair" if repair else "initial"
                )
            except MalformedOutput as exc:
                problem, raw = "output was not valid JSON", exc.raw_output
            else:
                try:
                    value = parse_output(response.text, schema)
                    return StructuredResult(value, response, tuple(attempts))
                except OutputParseError as exc:
                    problem, raw = exc.problem, response.text
                    attempts[-1] = dataclasses.replace(attempts[-1], outcome="invalid_output")

            if repair == self._policy.max_repair_retries:
                raise StructuredOutputError(
                    choice.provider, schema_name(schema), problem, raw[:2000]
                )
            if raw:
                conversation.append(Message("assistant", raw[:4000]))
            conversation.append(
                Message(
                    "user",
                    f"That response was invalid: {problem}. "
                    "Reply again with only the corrected JSON object.",
                )
            )
        raise AssertionError("unreachable")  # pragma: no cover

    async def _call(
        self,
        provider_name: ProviderName,
        request: LLMRequest,
        attempts: list[AttemptRecord],
        kind: AttemptKind,
    ) -> LLMResponse:
        provider = self._providers.get(provider_name)
        if provider is None:
            raise NoProviderConfigured(provider_name, f"No {provider_name} key is configured.")
        limiter = self._limiters.get(provider_name)
        retry = 0
        while True:
            if limiter:
                await limiter.acquire()
            started = time.perf_counter()
            try:
                response = await provider.generate(request)
            except LLMError as exc:
                attempts.append(
                    AttemptRecord(
                        provider_name,
                        request.model,
                        len(attempts) + 1,
                        kind,
                        "error",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        error_code=exc.code,
                    )
                )
                delay = self._policy.delay_before_retry(exc, retry)
                if delay is None:
                    raise
                await self._sleep(delay)
                retry += 1
                kind = "transient_retry"
                continue
            attempts.append(
                AttemptRecord(
                    provider_name,
                    request.model,
                    len(attempts) + 1,
                    kind,
                    "ok",
                    latency_ms=response.latency_ms,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
            )
            return response
