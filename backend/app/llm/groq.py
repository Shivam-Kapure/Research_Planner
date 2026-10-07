import re
import time
from typing import Any

import httpx2

from app.llm.errors import (
    LLMError,
    MalformedOutput,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderInvalidRequest,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.http import json_body, post_json, retry_after_seconds, scrub
from app.llm.types import ApiKeySource, LLMRequest, LLMResponse, ProviderName, TokenUsage

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_DAILY_LIMIT = re.compile(r"per day|\(RPD\)|\(TPD\)", re.IGNORECASE)


class GroqProvider:
    """Groq's OpenAI-compatible Chat Completions REST API (works with free-tier keys)."""

    def __init__(
        self,
        client: httpx2.AsyncClient,
        key_source: ApiKeySource,
        *,
        base_url: str = GROQ_BASE_URL,
        timeout_s: float = 60.0,
        reasoning_effort: str | None = None,
    ) -> None:
        self._client = client
        self._key_source = key_source
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        # For reasoning models (e.g. openai/gpt-oss-*): reasoning tokens count against
        # max_completion_tokens, so a lower effort leaves room for the JSON answer.
        self._reasoning_effort = reasoning_effort

    @property
    def name(self) -> ProviderName:
        return "groq"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_completion_tokens": request.max_output_tokens,
        }
        if request.json_mode:
            body["response_format"] = {"type": "json_object"}
        if self._reasoning_effort:
            body["reasoning_effort"] = self._reasoning_effort

        api_key = self._key_source()  # plaintext lives only in this call frame
        started = time.perf_counter()
        response = await post_json(
            self._client,
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            body=body,
            timeout_s=self._timeout_s,
            provider="groq",
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            raise _classify(response, api_key)

        data = json_body(response, "groq")
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
            usage = data.get("usage") or {}
            return LLMResponse(
                text=text,
                provider="groq",
                model=str(data.get("model") or request.model),
                usage=TokenUsage(usage.get("prompt_tokens"), usage.get("completion_tokens")),
                latency_ms=latency_ms,
                finish_reason=choice.get("finish_reason"),
            )
        except (KeyError, IndexError, TypeError, AttributeError):
            pass
        raise ProviderBadResponse("groq", "groq response is missing choices[0].message")


def _classify(response: httpx2.Response, api_key: str) -> LLMError:
    status = response.status_code
    error: dict[str, Any] = {}
    try:
        payload = response.json()
        error = payload.get("error") or {} if isinstance(payload, dict) else {}
    except ValueError:
        pass
    detail = scrub(str(error.get("message") or response.reason_phrase), api_key)
    message = f"groq HTTP {status}: {detail}"

    if status in (401, 403):
        return ProviderAuthError("groq", message, http_status=status)
    if status == 429:
        return ProviderRateLimited(
            "groq",
            message,
            retry_after_s=retry_after_seconds(response),
            daily_quota=bool(_DAILY_LIMIT.search(detail)),
        )
    if status == 400 and error.get("code") == "json_validate_failed":
        raw = str(error.get("failed_generation") or "")
        return MalformedOutput("groq", message, raw_output=scrub(raw, api_key))
    if status == 408:
        return ProviderTimeout("groq", message, http_status=status)
    if status >= 500:
        return ProviderUnavailable("groq", message, http_status=status)
    return ProviderInvalidRequest("groq", message, http_status=status)
