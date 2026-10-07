from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

ProviderName = Literal["groq", "gemini"]
PROVIDERS: tuple[ProviderName, ...] = ("groq", "gemini")

# Returns the decrypted API key on demand. Adapters call it per request and never store the
# result, so plaintext exists only for the duration of one HTTP call.
ApiKeySource = Callable[[], str]


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMRequest:
    messages: tuple[Message, ...]
    model: str
    temperature: float = 0.2
    max_output_tokens: int = 1024
    json_mode: bool = False

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("an LLM request needs at least one message")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if not 1 <= self.max_output_tokens <= 8192:
            raise ValueError("max_output_tokens must be between 1 and 8192")


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: ProviderName
    model: str
    usage: TokenUsage
    latency_ms: int
    finish_reason: str | None = None


class LLMProvider(Protocol):
    """Provider-neutral interface. Agents never see which concrete provider they use."""

    @property
    def name(self) -> ProviderName: ...

    async def generate(self, request: LLMRequest) -> LLMResponse: ...
