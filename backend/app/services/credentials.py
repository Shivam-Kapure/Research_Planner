import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProviderCredential
from app.db.repositories.credentials import CredentialRepository
from app.services.credential_crypto import CredentialCipher


class CredentialService:
    """Stores user provider API keys encrypted. Plaintext is never persisted or returned."""

    def __init__(self, db: AsyncSession, cipher: CredentialCipher) -> None:
        self._repo = CredentialRepository(db)
        self._cipher = cipher

    async def save(self, user_id: uuid.UUID, provider: str, api_key: str) -> ProviderCredential:
        return await self._repo.upsert(
            user_id, provider, self._cipher.encrypt(api_key), key_hint=api_key[-4:]
        )

    async def list(self, user_id: uuid.UUID) -> list[ProviderCredential]:
        return await self._repo.list_for_user(user_id)

    async def delete(self, user_id: uuid.UUID, provider: str) -> bool:
        return await self._repo.delete(user_id, provider)
