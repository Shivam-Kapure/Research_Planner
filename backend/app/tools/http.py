import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx2

from app.llm.rate_limit import RateLimiter
from app.tools.errors import (
    InvalidToolRequest,
    MalformedSourceResponse,
    SourceRateLimited,
    SourceTimeout,
    SourceUnavailable,
    ToolError,
)

MAX_JSON_BYTES = 2 * 1024 * 1024  # a 25-result search page is ~100 KB


class _StripUrlQuery(logging.Filter):
    """The HTTP client logs request URLs. Query strings can carry API keys (OpenAlex), emails
    or signed-URL tokens, so they are dropped from those log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_without_query(a) for a in record.args)
        return True


def _without_query(value: object) -> object:
    if isinstance(value, httpx2.URL):
        return str(value.copy_with(query=None, fragment=None))
    if isinstance(value, str) and value.startswith(("http://", "https://")) and "?" in value:
        return value.split("?", 1)[0]
    return value


def install_url_log_redaction() -> None:
    logger = logging.getLogger("httpx2")
    if not any(isinstance(f, _StripUrlQuery) for f in logger.filters):
        logger.addFilter(_StripUrlQuery())


install_url_log_redaction()


@dataclass(frozen=True)
class ToolRetryPolicy:
    """Bounded retries for transient failures: at most 2 retries, waits capped at 30 s."""

    max_retries: int = 2
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0

    def delay(self, error: ToolError, retry_index: int) -> float | None:
        if not error.retryable or retry_index >= self.max_retries:
            return None
        if isinstance(error, SourceRateLimited) and error.retry_after_s is not None:
            return error.retry_after_s if error.retry_after_s <= self.max_delay_s else None
        return min(self.base_delay_s * 2.0**retry_index, self.max_delay_s)


async def get_json(
    client: httpx2.AsyncClient,
    url: str,
    *,
    source: str,
    params: Mapping[str, str | int],
    headers: Mapping[str, str] | None = None,
    timeout_s: float,
    policy: ToolRetryPolicy,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    limiter: RateLimiter | None = None,
    max_bytes: int = MAX_JSON_BYTES,
) -> Any:
    """GET a JSON document with bounded size, timeout and retries (≤ 1 + max_retries calls)."""
    retry = 0
    while True:
        if limiter:
            await limiter.acquire()
        try:
            return await _get_json_once(
                client, url, source, params, headers or {}, timeout_s, max_bytes
            )
        except ToolError as exc:
            delay = policy.delay(exc, retry)
            if delay is None:
                raise
        await sleep(delay)
        retry += 1


async def _get_json_once(
    client: httpx2.AsyncClient,
    url: str,
    source: str,
    params: Mapping[str, str | int],
    headers: Mapping[str, str],
    timeout_s: float,
    max_bytes: int,
) -> Any:
    failure: ToolError
    try:
        async with client.stream(
            "GET", url, params=dict(params), headers=dict(headers), timeout=timeout_s
        ) as response:
            status = response.status_code
            if status >= 400:
                failure = _status_error(source, response)
            else:
                body = await read_bounded(response, max_bytes)
                if body is None:
                    failure = MalformedSourceResponse(
                        source, f"{source} response exceeded {max_bytes} bytes"
                    )
                else:
                    try:
                        return json.loads(body)
                    except ValueError:
                        failure = MalformedSourceResponse(source, f"{source} returned invalid JSON")
    except httpx2.TimeoutException:
        failure = SourceTimeout(source, f"{source} timed out after {timeout_s:g}s")
    except httpx2.TransportError as exc:
        failure = SourceUnavailable(source, f"{source} connection failed ({type(exc).__name__})")
    # Raised outside the except blocks: no __context__ that references the request/headers.
    raise failure


async def read_bounded(response: httpx2.Response, max_bytes: int) -> bytes | None:
    """Read a streamed body, stopping as soon as it exceeds `max_bytes` (returns None)."""
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > max_bytes:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _status_error(source: str, response: httpx2.Response) -> ToolError:
    status = response.status_code
    message = f"{source} HTTP {status}"
    if status == 429:
        return SourceRateLimited(source, message, retry_after_s=retry_after(response))
    if status >= 500:
        return SourceUnavailable(source, message, http_status=status)
    return InvalidToolRequest(source, message, http_status=status)


def retry_after(response: httpx2.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None
