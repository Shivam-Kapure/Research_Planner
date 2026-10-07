import pytest

from app.llm.errors import (
    MalformedOutput,
    NoProviderConfigured,
    ProviderAuthError,
    ProviderInvalidRequest,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
    StructuredOutputError,
)
from app.llm.gateway import LLMGateway, ModelChoice
from app.llm.rate_limit import RateLimiter, RateLimiters
from app.llm.retry import RetryPolicy
from app.llm.types import LLMProvider, Message, ProviderName
from app.schemas.contracts import ResearchRequest
from tests.llm_fakes import FakeClock, ScriptedProvider

pytestmark = pytest.mark.anyio

VALID = (
    '{"question": "How does sleep deprivation affect memory consolidation?", "max_iterations": 2}'
)
TOO_SHORT = '{"question": "short?"}'
USER = [Message("user", "Turn this into a research request.")]


def gateway(
    *providers: ScriptedProvider,
    models: dict[ProviderName, list[str]] | None = None,
    clock: FakeClock | None = None,
) -> LLMGateway:
    clock = clock or FakeClock()
    by_name: dict[ProviderName, LLMProvider] = {p.name: p for p in providers}
    return LLMGateway(
        by_name,
        models or {"groq": ["groq-a", "groq-b"], "gemini": ["gemini-a"]},
        sleep=clock.sleep,
    )


# ---- structured output ----


async def test_structured_success_requests_json_and_validates() -> None:
    provider = ScriptedProvider("groq", VALID)
    result = await gateway(provider).generate_structured(ResearchRequest, USER, role="planner")

    assert isinstance(result.value, ResearchRequest) and result.value.max_iterations == 2
    request = provider.requests[0]
    assert request.json_mode and request.model == "groq-a"
    assert request.messages[0].role == "system" and '"question"' in request.messages[0].content
    assert [(a.kind, a.outcome) for a in result.attempts] == [("initial", "ok")]
    assert result.attempts[0].input_tokens == 12 and result.attempts[0].output_tokens == 7


async def test_code_fenced_json_is_accepted() -> None:
    provider = ScriptedProvider("groq", f"```json\n{VALID}\n```")
    result = await gateway(provider).generate_structured(ResearchRequest, USER)
    assert result.value.question.startswith("How does sleep")


async def test_invalid_output_gets_one_repair_with_errors_fed_back() -> None:
    provider = ScriptedProvider("groq", TOO_SHORT, VALID)
    result = await gateway(provider).generate_structured(ResearchRequest, USER)

    assert result.value.max_iterations == 2
    assert [(a.kind, a.outcome) for a in result.attempts] == [
        ("initial", "invalid_output"),
        ("repair", "ok"),
    ]
    repair = provider.requests[1].messages
    assert repair[-2] == Message("assistant", TOO_SHORT)
    assert repair[-1].role == "user" and "question" in repair[-1].content
    assert "short?" not in repair[-1].content  # feedback names the field, not the value


async def test_repair_is_bounded_to_one_retry() -> None:
    provider = ScriptedProvider("groq", "not json", TOO_SHORT)
    with pytest.raises(StructuredOutputError) as exc_info:
        await gateway(provider).generate_structured(ResearchRequest, USER)
    assert len(provider.requests) == 2
    assert exc_info.value.schema_name == "research_request"
    assert exc_info.value.raw_excerpt == TOO_SHORT


async def test_provider_reported_malformed_json_is_repaired() -> None:
    provider = ScriptedProvider(
        "groq", MalformedOutput("groq", "bad json", raw_output='{"q":'), VALID
    )
    result = await gateway(provider).generate_structured(ResearchRequest, USER)
    assert result.value.max_iterations == 2
    assert provider.requests[1].messages[-2] == Message("assistant", '{"q":')


# ---- transient retries ----


async def test_transient_errors_are_retried_with_backoff() -> None:
    clock = FakeClock()
    provider = ScriptedProvider(
        "groq", ProviderUnavailable("groq", "503"), ProviderTimeout("groq", "slow"), VALID
    )
    result = await gateway(provider, clock=clock).generate_structured(ResearchRequest, USER)

    assert clock.sleeps == [1.0, 2.0]
    assert [(a.kind, a.outcome, a.error_code) for a in result.attempts] == [
        ("initial", "error", "provider_unavailable"),
        ("transient_retry", "error", "timeout"),
        ("transient_retry", "ok", None),
    ]


async def test_transient_retries_are_bounded_to_two() -> None:
    provider = ScriptedProvider("groq", *[ProviderUnavailable("groq", "503")] * 3, VALID)
    with pytest.raises(ProviderUnavailable):
        await gateway(provider).generate_structured(ResearchRequest, USER)
    assert len(provider.requests) == 3


async def test_worst_case_is_six_provider_calls() -> None:
    down = ProviderUnavailable("groq", "503")
    provider = ScriptedProvider("groq", down, down, "bad", down, down, "bad", VALID)
    with pytest.raises(StructuredOutputError):
        await gateway(provider).generate_structured(ResearchRequest, USER)
    assert len(provider.requests) == 6


async def test_rate_limit_honours_retry_after_within_cap() -> None:
    clock = FakeClock()
    provider = ScriptedProvider("groq", ProviderRateLimited("groq", "429", retry_after_s=7), VALID)
    await gateway(provider, clock=clock).generate_structured(ResearchRequest, USER)
    assert clock.sleeps == [7]


@pytest.mark.parametrize(
    "error",
    [
        ProviderRateLimited("groq", "429", retry_after_s=120),  # longer than the 60 s cap
        ProviderRateLimited("groq", "429", daily_quota=True),
        ProviderAuthError("groq", "401"),
        ProviderInvalidRequest("groq", "400"),
    ],
    ids=["retry-after-too-long", "daily-quota", "auth", "invalid-request"],
)
async def test_non_retryable_errors_fail_immediately(error: Exception) -> None:
    clock = FakeClock()
    provider = ScriptedProvider("groq", error, VALID)
    with pytest.raises(type(error)):
        await gateway(provider, clock=clock).generate_structured(ResearchRequest, USER)
    assert len(provider.requests) == 1 and clock.sleeps == []


def test_retry_policy_limits() -> None:
    policy = RetryPolicy()
    down = ProviderUnavailable("groq", "503")
    assert [policy.delay_before_retry(down, i) for i in range(3)] == [1.0, 2.0, None]


# ---- provider configuration ----


async def test_no_provider_configured_fails_only_when_called() -> None:
    empty = LLMGateway({}, {"groq": ["groq-a"], "gemini": ["gemini-a"]})  # construction is fine
    assert empty.available == ()
    with pytest.raises(NoProviderConfigured, match="No LLM provider key"):
        empty.candidates()
    with pytest.raises(NoProviderConfigured):
        await empty.generate_structured(ResearchRequest, USER)


def test_key_without_configured_models_is_reported() -> None:
    gw = gateway(ScriptedProvider("groq"), models={"groq": [], "gemini": []})
    with pytest.raises(NoProviderConfigured, match="GROQ_MODELS"):
        gw.candidates()


def test_only_groq_configured_serves_every_role() -> None:
    gw = gateway(ScriptedProvider("groq"))
    assert gw.available == ("groq",)
    # synthesis prefers Gemini but falls back to Groq when that is all the user has
    assert gw.candidates("synthesis") == [
        ModelChoice("groq", "groq-a"),
        ModelChoice("groq", "groq-b"),
    ]


async def test_only_gemini_configured_serves_every_role() -> None:
    provider = ScriptedProvider("gemini", VALID)
    gw = gateway(provider)
    assert gw.available == ("gemini",)
    assert gw.candidates("planner") == [ModelChoice("gemini", "gemini-a")]
    await gw.generate_structured(ResearchRequest, USER, role="planner")
    assert provider.requests[0].model == "gemini-a"


def test_both_providers_follow_role_preference() -> None:
    gw = gateway(ScriptedProvider("groq"), ScriptedProvider("gemini"))
    assert [c.provider for c in gw.candidates("analysis")] == ["groq", "groq", "gemini"]
    assert [c.provider for c in gw.candidates("writer")] == ["gemini", "groq", "groq"]


async def test_explicit_choice_is_used() -> None:
    groq, gem = ScriptedProvider("groq"), ScriptedProvider("gemini", VALID)
    await gateway(groq, gem).generate_structured(
        ResearchRequest, USER, choice=ModelChoice("gemini", "gemini-a")
    )
    assert groq.requests == [] and gem.requests[0].model == "gemini-a"


# ---- rate limiting ----


async def test_rate_limiter_paces_requests() -> None:
    clock = FakeClock()
    limiter = RateLimiter(60, clock=clock, sleep=clock.sleep)  # one request per second
    waits = [await limiter.acquire() for _ in range(3)]
    assert waits == [0.0, 1.0, 1.0]


async def test_gateway_acquires_a_slot_for_every_attempt() -> None:
    clock = FakeClock()
    limiter = RateLimiter(30, clock=clock, sleep=clock.sleep)  # one per 2 s
    provider = ScriptedProvider("groq", ProviderUnavailable("groq", "503"), VALID)
    gw = LLMGateway(
        {"groq": provider}, {"groq": ["groq-a"]}, limiters={"groq": limiter}, sleep=clock.sleep
    )
    await gw.generate_structured(ResearchRequest, USER)
    # limiter (0) + backoff (1 s) + limiter waits for the remaining 1 s of its 2 s interval
    assert clock.sleeps == [1.0, 1.0]


def test_rate_limiters_are_per_provider_and_key_owner() -> None:
    limiters = RateLimiters({"groq": 20, "gemini": 8})
    assert limiters.get("groq", "user-1") is limiters.get("groq", "user-1")
    assert limiters.get("groq", "user-1") is not limiters.get("groq", "user-2")
    assert limiters.get("groq", "user-1") is not limiters.get("gemini", "user-1")
