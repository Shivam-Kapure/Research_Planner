import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProviderCredential
from app.db.repositories.credentials import CredentialRepository
from app.services.credential_crypto import CredentialCipher


class EncryptedApiKey:
    """A stored provider key that stays encrypted until `reveal()` is called.

    LLM adapters hold this (ciphertext + the shared cipher), never the plaintext; they call
    `reveal()` per request so the decrypted key exists only for that request.
    """

    __slots__ = ("_cipher", "_ciphertext", "provider")

    def __init__(self, provider: str, ciphertext: bytes, cipher: CredentialCipher) -> None:
        self.provider = provider
        self._ciphertext = ciphertext
        self._cipher = cipher

    def reveal(self) -> str:
        return self._cipher.decrypt(self._ciphertext)

    def __repr__(self) -> str:
        return f"EncryptedApiKey(provider={self.provider!r})"


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

    async def set_status(
        self, user_id: uuid.UUID, provider: str, status: str
    ) -> ProviderCredential | None:
        return await self._repo.set_status(user_id, provider, status)

    async def delete(self, user_id: uuid.UUID, provider: str) -> bool:
        return await self._repo.delete(user_id, provider)

    async def load_encrypted(self, user_id: uuid.UUID) -> dict[str, EncryptedApiKey]:
        """The user's usable keys, still encrypted. Keys marked invalid are skipped."""
        return {
            c.provider: EncryptedApiKey(c.provider, c.ciphertext, self._cipher)
            for c in await self._repo.list_for_user(user_id)
            if c.status != "invalid"
        }
