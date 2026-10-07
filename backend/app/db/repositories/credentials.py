import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProviderCredential


class CredentialRepository:
    """All queries are scoped by user_id, so one user can never read another's credentials."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: uuid.UUID) -> list[ProviderCredential]:
        result = await self._session.scalars(
            select(ProviderCredential).where(ProviderCredential.user_id == user_id)
        )
        return list(result)

    async def upsert(
        self, user_id: uuid.UUID, provider: str, ciphertext: bytes, key_hint: str
    ) -> ProviderCredential:
        # Atomic insert-or-replace on (user_id, provider); a new key resets validation state.
        stmt = (
            insert(ProviderCredential)
            .values(user_id=user_id, provider=provider, ciphertext=ciphertext, key_hint=key_hint)
            .on_conflict_do_update(
                constraint="uq_user_provider_credentials_user_provider",
                set_={
                    "ciphertext": ciphertext,
                    "key_hint": key_hint,
                    "status": "unverified",
                    "validated_at": None,
                    "updated_at": func.now(),
                },
            )
            .returning(ProviderCredential)
        )
        credential = (
            await self._session.scalars(stmt, execution_options={"populate_existing": True})
        ).one()
        return credential

    async def delete(self, user_id: uuid.UUID, provider: str) -> bool:
        result = await self._session.execute(
            delete(ProviderCredential)
            .where(ProviderCredential.user_id == user_id, ProviderCredential.provider == provider)
            .returning(ProviderCredential.id)
        )
        return result.first() is not None
