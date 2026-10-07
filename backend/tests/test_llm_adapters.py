import logging
from typing import Any

import httpx2
import pytest

from app.llm.errors import (
    LLMError,
    MalformedOutput,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderContentBlocked,
    ProviderInvalidRequest,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.gemini import GeminiProvider
from app.llm.groq import GroqProvider
from app.llm.types import LLMRequest, Message
from tests.llm_fakes import (
    GEMINI_TEST_KEY,
    GROQ_TEST_KEY,
    CountingKeySource,
    Recorder,
    json_response,
)

pytestmark = pytest.mark.anyio

REQUEST = LLMRequest(
    (
        Message("system", "Return JSON."),
        Message("user", "Plan a review."),
        Message("assistant", "{}"),
    ),
    model="test-model-id",
    temperature=0.1,
    max_output_tokens=256,
    json_mode=True,
)

GROQ_OK = {
    "model": "test-model-id",
    "choices": [{"message": {"role": "assistant", "content": '{"a": 1}'}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 31, "completion_tokens": 9},
}
GEMINI_OK = {
    "candidates": [
        {
            "content": {
                "parts": [{"text": "hidden reasoning", "thought": True}, {"text": '{"a": 1}'}]
            },
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 40, "candidatesTokenCount": 8, "thoughtsTokenCount": 5},
    "modelVersion": "test-model-id",
}


def groq(recorder: Recorder, key: Any = None) -> GroqProvider:
    return GroqProvider(recorder.client(), key or CountingKeySource(GROQ_TEST_KEY))


def gemini(recorder: Recorder, key: Any = None, **kwargs: Any) -> GeminiProvider:
    return GeminiProvider(recorder.client(), key or CountingKeySource(GEMINI_TEST_KEY), **kwargs)


def assert_no_secret(error: LLMError, secret: str) -> None:
    assert secret not in str(error) and secret not in repr(error) and secret not in error.message
    assert error.__cause__ is None and error.__context__ is None


# ---------------- Groq ----------------


async def test_groq_request_and_response_mapping() -> None:
    recorder = Recorder(json_response(200, GROQ_OK))
    response = await groq(recorder).generate(REQUEST)

    sent = recorder.requests[0]
    assert str(sent.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert sent.headers["authorization"] == f"Bearer {GROQ_TEST_KEY}"
    assert GROQ_TEST_KEY not in str(sent.url)
    body = recorder.body()
    assert body["model"] == "test-model-id"
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_completion_tokens"] == 256 and body["temperature"] == 0.1
    assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant"]

    assert response.text == '{"a": 1}' and response.provider == "groq"
    assert response.usage.input_tokens == 31 and response.usage.output_tokens == 9
    assert response.finish_reason == "stop" and response.latency_ms >= 0


async def test_groq_does_not_request_json_mode_unless_asked() -> None:
    recorder = Recorder(json_response(200, GROQ_OK))
    await groq(recorder).generate(LLMRequest((Message("user", "hi"),), model="m"))
    assert "response_format" not in recorder.body()


@pytest.mark.parametrize(
    ("response", "error_type", "retryable"),
    [
        (json_response(401, {"error": {"message": "Invalid API Key"}}), ProviderAuthError, False),
        (json_response(403, {"error": {"message": "forbidden"}}), ProviderAuthError, False),
        (json_response(400, {"error": {"message": "bad"}}), ProviderInvalidRequest, False),
        (
            json_response(404, {"error": {"message": "model not found"}}),
            ProviderInvalidRequest,
            False,
        ),
        (json_response(413, {"error": {"message": "too large"}}), ProviderInvalidRequest, False),
        (json_response(500, {"error": {"message": "oops"}}), ProviderUnavailable, True),
        (json_response(503, {"error": {"message": "over capacity"}}), ProviderUnavailable, True),
        (httpx2.Response(200, text="<html>not json</html>"), ProviderBadResponse, True),
        (json_response(200, {"choices": []}), ProviderBadResponse, True),
    ],
)
async def test_groq_error_classification(
    response: httpx2.Response, error_type: type[LLMError], retryable: bool
) -> None:
    with pytest.raises(error_type) as exc_info:
        await groq(Recorder(response)).generate(REQUEST)
    assert exc_info.value.retryable is retryable
    assert exc_info.value.provider == "groq"


async def test_groq_rate_limit_per_minute_is_retryable_with_retry_after() -> None:
    response = json_response(
        429,
        {"error": {"message": "Rate limit reached on tokens per minute (TPM). Try again in 7s."}},
        headers={"retry-after": "7"},
    )
    with pytest.raises(ProviderRateLimited) as exc_info:
        await groq(Recorder(response)).generate(REQUEST)
    assert exc_info.value.retryable and exc_info.value.retry_after_s == 7
    assert exc_info.value.code == "rate_limited"


async def test_groq_daily_quota_is_not_retryable() -> None:
    response = json_response(
        429, {"error": {"message": "Rate limit reached on requests per day (RPD): Limit 1000"}}
    )
    with pytest.raises(ProviderRateLimited) as exc_info:
        await groq(Recorder(response)).generate(REQUEST)
    assert exc_info.value.daily_quota and not exc_info.value.retryable
    assert exc_info.value.code == "daily_quota_exhausted"


async def test_groq_json_validate_failed_becomes_malformed_output() -> None:
    response = json_response(
        400,
        {
            "error": {
                "message": "Failed to generate JSON",
                "code": "json_validate_failed",
                "failed_generation": '{"a": ',
            }
        },
    )
    with pytest.raises(MalformedOutput) as exc_info:
        await groq(Recorder(response)).generate(REQUEST)
    assert exc_info.value.raw_output == '{"a": '
    assert not exc_info.value.retryable


@pytest.mark.parametrize(
    ("exc", "error_type"),
    [
        (httpx2.ReadTimeout("timed out"), ProviderTimeout),
        (httpx2.ConnectError("connection refused"), ProviderUnavailable),
    ],
)
async def test_groq_transport_failures(exc: Exception, error_type: type[LLMError]) -> None:
    with pytest.raises(error_type) as exc_info:
        await groq(Recorder(exc)).generate(REQUEST)
    assert exc_info.value.retryable
    assert_no_secret(exc_info.value, GROQ_TEST_KEY)


async def test_groq_errors_never_expose_the_key() -> None:
    # A provider that (wrongly) echoes the key back must not leak it through our error.
    response = json_response(401, {"error": {"message": f"Invalid API Key: {GROQ_TEST_KEY}"}})
    with pytest.raises(ProviderAuthError) as exc_info:
        await groq(Recorder(response)).generate(REQUEST)
    assert_no_secret(exc_info.value, GROQ_TEST_KEY)
    assert "[REDACTED]" in exc_info.value.message


# ---------------- Gemini ----------------


async def test_gemini_request_and_response_mapping() -> None:
    recorder = Recorder(json_response(200, GEMINI_OK))
    response = await gemini(recorder, thinking_budget=0).generate(REQUEST)

    sent = recorder.requests[0]
    assert str(sent.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/test-model-id:generateContent"
    )
    assert sent.headers["x-goog-api-key"] == GEMINI_TEST_KEY
    assert GEMINI_TEST_KEY not in str(sent.url)  # never in the query string
    assert "authorization" not in sent.headers
    body = recorder.body()
    assert body["systemInstruction"] == {"parts": [{"text": "Return JSON."}]}
    assert [c["role"] for c in body["contents"]] == ["user", "model"]
    assert body["generationConfig"] == {
        "temperature": 0.1,
        "maxOutputTokens": 256,
        "responseMimeType": "application/json",
        "thinkingConfig": {"thinkingBudget": 0},
    }

    assert response.text == '{"a": 1}'  # thought parts excluded
    assert response.usage.input_tokens == 40 and response.usage.output_tokens == 13
    assert response.finish_reason == "STOP" and response.provider == "gemini"


async def test_gemini_strips_models_prefix_and_rejects_unsafe_model_ids() -> None:
    recorder = Recorder(json_response(200, GEMINI_OK))
    await gemini(recorder).generate(LLMRequest((Message("user", "hi"),), model="models/abc-1"))
    assert recorder.requests[0].url.path.endswith("/models/abc-1:generateContent")

    untouched = Recorder()
    with pytest.raises(ProviderInvalidRequest):
        await gemini(untouched).generate(LLMRequest((Message("user", "hi"),), model="../admin"))
    assert untouched.requests == []


def _gemini_error(
    status: int, reason: str | None = None, details: list[dict[str, Any]] | None = None
) -> httpx2.Response:
    items = list(details or [])
    if reason:
        items.append({"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason})
    return json_response(status, {"error": {"code": status, "message": "error", "details": items}})


@pytest.mark.parametrize(
    ("response", "error_type", "retryable"),
    [
        (_gemini_error(400, "API_KEY_INVALID"), ProviderAuthError, False),
        (_gemini_error(403), ProviderAuthError, False),
        (_gemini_error(400), ProviderInvalidRequest, False),
        (_gemini_error(404), ProviderInvalidRequest, False),
        (_gemini_error(500), ProviderUnavailable, True),
        (_gemini_error(503), ProviderUnavailable, True),
        (json_response(200, {"candidates": []}), ProviderBadResponse, True),
        (
            json_response(200, {"promptFeedback": {"blockReason": "SAFETY"}}),
            ProviderContentBlocked,
            False,
        ),
        (
            json_response(
                200, {"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]}
            ),
            ProviderContentBlocked,
            False,
        ),
    ],
)
async def test_gemini_error_classification(
    response: httpx2.Response, error_type: type[LLMError], retryable: bool
) -> None:
    with pytest.raises(error_type) as exc_info:
        await gemini(Recorder(response)).generate(REQUEST)
    assert exc_info.value.retryable is retryable


async def test_gemini_rate_limits_use_retry_info_and_detect_daily_quota() -> None:
    retry_info = {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "41s"}
    per_minute = {
        "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]
    }
    per_day = {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}

    with pytest.raises(ProviderRateLimited) as minute:
        await gemini(Recorder(_gemini_error(429, details=[per_minute, retry_info]))).generate(
            REQUEST
        )
    assert minute.value.retryable and minute.value.retry_after_s == 41

    with pytest.raises(ProviderRateLimited) as day:
        await gemini(Recorder(_gemini_error(429, details=[per_day, retry_info]))).generate(REQUEST)
    assert day.value.daily_quota and not day.value.retryable


async def test_gemini_timeout_and_key_scrubbing() -> None:
    with pytest.raises(ProviderTimeout) as timeout:
        await gemini(Recorder(httpx2.ReadTimeout("slow"))).generate(REQUEST)
    assert_no_secret(timeout.value, GEMINI_TEST_KEY)

    echo = json_response(
        400,
        {
            "error": {
                "message": f"API key not valid: {GEMINI_TEST_KEY}",
                "details": [{"reason": "API_KEY_INVALID"}],
            }
        },
    )
    with pytest.raises(ProviderAuthError) as auth:
        await gemini(Recorder(echo)).generate(REQUEST)
    assert_no_secret(auth.value, GEMINI_TEST_KEY)


# ---------------- credential handling (both adapters) ----------------


@pytest.mark.parametrize(
    ("factory", "ok", "secret"),
    [(groq, GROQ_OK, GROQ_TEST_KEY), (gemini, GEMINI_OK, GEMINI_TEST_KEY)],
    ids=["groq", "gemini"],
)
async def test_key_is_fetched_per_request_and_never_retained_or_logged(
    factory: Any, ok: dict[str, Any], secret: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    source = CountingKeySource(secret)
    provider = factory(Recorder(json_response(200, ok), json_response(200, ok)), source)

    first = await provider.generate(REQUEST)
    await provider.generate(REQUEST)

    assert source.calls == 2  # decrypted on demand for each request, not cached
    state = repr(vars(provider)) + repr(provider) + repr(first)
    assert secret not in state
    assert caplog.records  # HTTP client logging was captured
    assert secret not in caplog.text
