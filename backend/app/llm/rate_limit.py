import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping

from app.llm.types import ProviderName


class RateLimiter:
    """Paces calls to at most `requests_per_minute`, waiting instead of provoking 429s."""

    def __init__(
        self,
        requests_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if requests_per_minute < 1:
            raise ValueError("requests_per_minute must be at least 1")
        self._interval = 60.0 / requests_per_minute
        self._clock = clock
        self._sleep = sleep
        self._next_slot = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """Wait for the next slot; returns how long the caller waited (seconds)."""
        async with self._lock:
            now = self._clock()
            wait = max(0.0, self._next_slot - now)
            if wait:
                await self._sleep(wait)
            self._next_slot = now + wait + self._interval
            return wait


class RateLimiters:
    """Process-wide limiters, one per (provider, key owner): free-tier limits apply per key."""

    def __init__(self, requests_per_minute: Mapping[ProviderName, int]) -> None:
        self._rpm = dict(requests_per_minute)
        self._limiters: dict[tuple[ProviderName, str], RateLimiter] = {}

    def get(self, provider: ProviderName, owner: str) -> RateLimiter:
        key = (provider, owner)
        if key not in self._limiters:
            self._limiters[key] = RateLimiter(self._rpm[provider])
        return self._limiters[key]
