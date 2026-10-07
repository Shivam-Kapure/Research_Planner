from dataclasses import dataclass

from app.llm.errors import LLMError, ProviderRateLimited


@dataclass(frozen=True)
class RetryPolicy:
    """Architecture §6.1: at most 2 transient retries and 1 structured-output repair per call;
    never wait more than 60 s for a provider."""

    max_transient_retries: int = 2
    max_repair_retries: int = 1
    base_delay_s: float = 1.0
    max_delay_s: float = 60.0

    def delay_before_retry(self, error: LLMError, retry_index: int) -> float | None:
        """Seconds to wait before retry number `retry_index` (0-based), or None to give up."""
        if not error.retryable or retry_index >= self.max_transient_retries:
            return None
        if isinstance(error, ProviderRateLimited) and error.retry_after_s is not None:
            if error.retry_after_s > self.max_delay_s:
                return None  # the provider wants longer than a run can afford to wait
            return error.retry_after_s
        return min(self.base_delay_s * 2.0**retry_index, self.max_delay_s)
