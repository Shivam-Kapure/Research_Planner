from typing import Any

import httpx2

from app.llm.errors import ProviderBadResponse, ProviderTimeout, ProviderUnavailable

_MAX_MESSAGE = 300


def scrub(text: str, secret: str) -> str:
    """Remove the request's API key from provider-supplied text and bound its length."""
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text[:_MAX_MESSAGE]


async def post_json(
    client: httpx2.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_s: float,
    provider: str,
) -> httpx2.Response:
    """POST JSON, translating transport failures into provider-neutral errors.

    The error is raised outside the `except` block so it carries no `__context__` that could
    reference the request (and therefore its auth headers).
    """
    failure: ProviderTimeout | ProviderUnavailable
    try:
        return await client.post(url, headers=headers, json=body, timeout=timeout_s)
    except httpx2.TimeoutException:
        failure = ProviderTimeout(provider, f"{provider} request timed out after {timeout_s:g}s")
    except httpx2.TransportError as exc:
        failure = ProviderUnavailable(
            provider, f"{provider} connection failed ({type(exc).__name__})"
        )
    raise failure


def json_body(response: httpx2.Response, provider: str) -> Any:
    try:
        return response.json()
    except ValueError:
        pass
    raise ProviderBadResponse(
        provider, f"{provider} returned a non-JSON response", http_status=response.status_code
    )


def retry_after_seconds(response: httpx2.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None
