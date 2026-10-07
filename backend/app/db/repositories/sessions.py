import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserSession


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: uuid.UUID, token_hash: str, expires_at: datetime) -> None:
        self._session.add(
            UserSession(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        )
        await self._session.flush()

    async def get_active_with_user(
        self, token_hash: str, now: datetime
    ) -> tuple[UserSession, User] | None:
        row = (
            await self._session.execute(
                select(UserSession, User)
                .join(User, User.id == UserSession.user_id)
                .where(
                    UserSession.token_hash == token_hash,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                )
            )
        ).first()
        return (row[0], row[1]) if row else None

    async def extend(self, user_session: UserSession, expires_at: datetime) -> None:
        user_session.expires_at = expires_at
        await self._session.flush()

    async def revoke(self, token_hash: str, now: datetime) -> None:
        await self._session.execute(
            update(UserSession)
            .where(UserSession.token_hash == token_hash, UserSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
