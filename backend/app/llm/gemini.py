import re
import time
from typing import Any

import httpx2

from app.llm.errors import (
    LLMError,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderContentBlocked,
    ProviderInvalidRequest,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.http import json_body, post_json, retry_after_seconds, scrub
from app.llm.types import ApiKeySource, LLMRequest, LLMResponse, ProviderName, TokenUsage

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-_]{0,99}$")
_BLOCKED_FINISH = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}


class GeminiProvider:
    """Gemini API `generateContent` REST endpoint (works with free-tier keys).

    The key travels in the `x-goog-api-key` header, never in the URL.
    """

    def __init__(
        self,
        client: httpx2.AsyncClient,
        key_source: ApiKeySource,
        *,
        base_url: str = GEMINI_BASE_URL,
        timeout_s: float = 60.0,
        thinking_budget: int | None = None,
    ) -> None:
        self._client = client
        self._key_source = key_source
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._thinking_budget = thinking_budget

    @property
    def name(self) -> ProviderName:
        return "gemini"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        model = request.model.removeprefix("models/")
        if not _MODEL_ID.match(model):
            raise ProviderInvalidRequest("gemini", "invalid gemini model id")

        config: dict[str, Any] = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_output_tokens,
        }
        if request.json_mode:
            config["responseMimeType"] = "application/json"
        if self._thinking_budget is not None:
            config["thinkingConfig"] = {"thinkingBudget": self._thinking_budget}
        body: dict[str, Any] = {
            "contents": [
                {
                    "role": "model" if m.role == "assistant" else "user",
                    "parts": [{"text": m.content}],
                }
                for m in request.messages
                if m.role != "system"
            ],
            "generationConfig": config,
        }
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        api_key = self._key_source()  # plaintext lives only in this call frame
        started = time.perf_counter()
        response = await post_json(
            self._client,
            f"{self._base_url}/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key},
            body=body,
            timeout_s=self._timeout_s,
            provider="gemini",
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            raise _classify(response, api_key)
        return _parse(json_body(response, "gemini"), model, latency_ms)


def _parse(data: Any, model: str, latency_ms: int) -> LLMResponse:
    if not isinstance(data, dict):
        raise ProviderBadResponse("gemini", "gemini response is not an object")
    block = (data.get("promptFeedback") or {}).get("blockReason")
    if block:
        raise ProviderContentBlocked("gemini", f"gemini blocked the prompt ({block})")
    candidates = data.get("candidates") or []
    if not candidates or not isinstance(candidates[0], dict):
        raise ProviderBadResponse("gemini", "gemini response has no candidates")
    candidate = candidates[0]
    finish = candidate.get("finishReason")
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
    if not text and finish in _BLOCKED_FINISH:
        raise ProviderContentBlocked("gemini", f"gemini withheld the response ({finish})")
    usage = data.get("usageMetadata") or {}
    output_tokens = usage.get("candidatesTokenCount")
    if output_tokens is not None and usage.get("thoughtsTokenCount"):
        output_tokens += usage["thoughtsTokenCount"]  # thinking counts against the quota too
    return LLMResponse(
        text=text,
        provider="gemini",
        model=str(data.get("modelVersion") or model),
        usage=TokenUsage(usage.get("promptTokenCount"), output_tokens),
        latency_ms=latency_ms,
        finish_reason=finish,
    )


def _classify(response: httpx2.Response, api_key: str) -> LLMError:
    status = response.status_code
    error: dict[str, Any] = {}
    try:
        payload = response.json()
        error = payload.get("error") or {} if isinstance(payload, dict) else {}
    except ValueError:
        pass
    details = [d for d in error.get("details") or [] if isinstance(d, dict)]
    reasons = {str(d.get("reason")) for d in details}
    detail = scrub(str(error.get("message") or response.reason_phrase), api_key)
    message = f"gemini HTTP {status}: {detail}"

    if status in (401, 403) or "API_KEY_INVALID" in reasons:
        return ProviderAuthError("gemini", message, http_status=status)
    if status == 429:
        return ProviderRateLimited(
            "gemini",
            message,
            retry_after_s=_retry_delay(details) or retry_after_seconds(response),
            daily_quota=_is_daily_quota(details),
        )
    if status == 408:
        return ProviderTimeout("gemini", message, http_status=status)
    if status >= 500:
        return ProviderUnavailable("gemini", message, http_status=status)
    return ProviderInvalidRequest("gemini", message, http_status=status)


def _retry_delay(details: list[dict[str, Any]]) -> float | None:
    for d in details:
        delay = d.get("retryDelay")
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                return None
    return None


def _is_daily_quota(details: list[dict[str, Any]]) -> bool:
    for d in details:
        for violation in d.get("violations") or []:
            if isinstance(violation, dict) and "PerDay" in str(violation.get("quotaId", "")):
                return True
    return False
