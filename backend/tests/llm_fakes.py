"""Test doubles for the LLM layer. No test ever calls a real provider API."""

import json
from typing import Any

import httpx2

from app.llm.types import LLMRequest, LLMResponse, ProviderName, TokenUsage

# Fake keys shaped like real ones (so the redaction patterns are exercised) but not real.
GROQ_TEST_KEY = "gsk_TESTONLY_" + "Zq8Xw7Vu6Ts5Rq4Po3Nm2Lk1"
GEMINI_TEST_KEY = "AIza" + "TESTONLY_" + "x9Y8z7W6v5U4t3S2r1Q0"


class Recorder:
    """httpx2 MockTransport handler that records requests and replays scripted responses."""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self))

    def body(self, index: int = -1) -> Any:
        return json.loads(self.requests[index].content)


def json_response(
    status: int, payload: Any, headers: dict[str, str] | None = None
) -> httpx2.Response:
    return httpx2.Response(status, json=payload, headers=headers)


class CountingKeySource:
    def __init__(self, key: str) -> None:
        self._key = key
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self._key


class ScriptedProvider:
    """LLMProvider whose responses (text or exceptions) are scripted per call."""

    def __init__(self, name: ProviderName, *script: str | Exception) -> None:
        self._name = name
        self.script = list(script)
        self.requests: list[LLMRequest] = []

    @property
    def name(self) -> ProviderName:
        return self._name

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(item, self._name, request.model, TokenUsage(12, 7), latency_ms=5)


class FakeClock:
    """Monotonic clock advanced only by the paired sleep, so waits are exact and instant."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
