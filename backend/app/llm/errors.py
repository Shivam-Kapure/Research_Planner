"""Provider-neutral LLM errors. Messages are built by this package from status codes and
scrubbed provider text; they never contain credentials or request headers."""


class LLMError(Exception):
    code = "llm_error"
    retryable = False

    def __init__(self, provider: str | None, message: str, *, http_status: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.message = message
        self.http_status = http_status
        # AttemptRecords made before this error was raised (set by LLMGateway), so callers can
        # trace failed calls too. Metadata only.
        self.attempts: tuple[object, ...] = ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(provider={self.provider!r}, code={self.code!r})"


class ProviderAuthError(LLMError):
    """Key missing, invalid, revoked or not permitted. Never retried."""

    code = "auth_failed"


class ProviderInvalidRequest(LLMError):
    """Bad request, unknown model, or request too large. Never retried."""

    code = "invalid_request"


class ProviderRateLimited(LLMError):
    code = "rate_limited"

    def __init__(
        self,
        provider: str | None,
        message: str,
        *,
        retry_after_s: float | None = None,
        daily_quota: bool = False,
        http_status: int | None = 429,
    ):
        super().__init__(provider, message, http_status=http_status)
        self.retry_after_s = retry_after_s
        self.daily_quota = daily_quota
        if daily_quota:
            # A daily free-tier quota will not recover within a run: fall back, don't wait.
            self.code = "daily_quota_exhausted"

    @property
    def retryable(self) -> bool:  # type: ignore[override]
        return not self.daily_quota


class ProviderTimeout(LLMError):
    code = "timeout"
    retryable = True


class ProviderUnavailable(LLMError):
    code = "provider_unavailable"
    retryable = True


class ProviderBadResponse(LLMError):
    """The provider answered with something unusable (not JSON, missing fields)."""

    code = "bad_response"
    retryable = True


class ProviderContentBlocked(LLMError):
    code = "content_blocked"


class MalformedOutput(LLMError):
    """The provider itself rejected the model's output as invalid JSON (e.g. Groq
    json_validate_failed). Handled by the structured-output repair step, not retried as-is."""

    code = "malformed_output"

    def __init__(self, provider: str | None, message: str, *, raw_output: str = ""):
        super().__init__(provider, message, http_status=400)
        self.raw_output = raw_output


class StructuredOutputError(LLMError):
    """The model's output still failed schema validation after the repair retry."""

    code = "structured_output_invalid"

    def __init__(self, provider: str | None, schema_name: str, problem: str, raw_excerpt: str):
        super().__init__(provider, f"{schema_name}: {problem}")
        self.schema_name = schema_name
        self.problem = problem
        self.raw_excerpt = raw_excerpt


class NoProviderConfigured(LLMError):
    code = "no_provider_configured"
