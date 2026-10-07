import uuid

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.gateway import LLMGateway
from app.llm.gemini import GeminiProvider
from app.llm.groq import GroqProvider
from app.llm.rate_limit import RateLimiters
from app.llm.types import LLMProvider, ProviderName
from app.services.credential_crypto import CredentialCipher
from app.services.credentials import CredentialService


def rate_limiters_from(settings: Settings) -> RateLimiters:
    return RateLimiters(
        {"groq": settings.groq_requests_per_minute, "gemini": settings.gemini_requests_per_minute}
    )


async def build_gateway_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    cipher: CredentialCipher,
    settings: Settings,
    http_client: httpx2.AsyncClient,
    limiters: RateLimiters,
) -> LLMGateway:
    """Wire the user's stored keys (still encrypted) into provider adapters.

    Works with Groq only, Gemini only, or both. With no keys the gateway is still built;
    the first LLM call then fails with NoProviderConfigured.
    """
    keys = await CredentialService(db, cipher).load_encrypted(user_id)
    providers: dict[ProviderName, LLMProvider] = {}
    if "groq" in keys:
        providers["groq"] = GroqProvider(
            http_client,
            keys["groq"].reveal,
            timeout_s=settings.llm_request_timeout_s,
            reasoning_effort=settings.groq_reasoning_effort,
        )
    if "gemini" in keys:
        providers["gemini"] = GeminiProvider(
            http_client,
            keys["gemini"].reveal,
            timeout_s=settings.llm_request_timeout_s,
            thinking_budget=settings.gemini_thinking_budget,
            thinking_level=settings.gemini_thinking_level,
        )
    return LLMGateway(
        providers,
        {"groq": settings.groq_models, "gemini": settings.gemini_models},
        limiters={name: limiters.get(name, str(user_id)) for name in providers},
    )
