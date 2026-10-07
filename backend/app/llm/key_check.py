"""Minimal provider-key validation: one cheap authenticated GET to the provider's model list.

Used when a user saves a key, so a bad key is reported immediately instead of failing a run.
The key is sent only in the auth header, never logged, and never part of the outcome.
"""

from typing import Literal

import httpx2

from app.llm.gemini import GEMINI_BASE_URL
from app.llm.groq import GROQ_BASE_URL
from app.llm.types import ProviderName

KeyStatus = Literal["valid", "invalid", "unverified"]


async def check_provider_key(
    client: httpx2.AsyncClient, provider: ProviderName, api_key: str, *, timeout_s: float = 10.0
) -> KeyStatus:
    """valid (200), invalid (provider rejected the key) or unverified (provider unreachable or
    an unexpected answer — the key is kept and can still be used)."""
    if provider == "groq":
        url, headers = f"{GROQ_BASE_URL}/models", {"Authorization": f"Bearer {api_key}"}
    else:
        url, headers = f"{GEMINI_BASE_URL}/models", {"x-goog-api-key": api_key}
    try:
        response = await client.get(url, headers=headers, timeout=timeout_s)
    except httpx2.HTTPError:
        return "unverified"
    if response.status_code == 200:
        return "valid"
    if response.status_code in (401, 403) or (
        response.status_code == 400 and b"API_KEY_INVALID" in response.content
    ):
        return "invalid"
    return "unverified"
