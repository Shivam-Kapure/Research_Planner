import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.repositories.sessions import SessionRepository
from app.db.repositories.users import UserRepository
from app.services import passwords


@dataclass(frozen=True)
class NewSession:
    token: str  # raw token: only ever placed in the httpOnly cookie
    expires_at: datetime


@dataclass(frozen=True)
class ResolvedSession:
    user: User
    token_hash: str
    expires_at: datetime
    refreshed: bool  # True when the sliding expiry was extended


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, db: AsyncSession, session_ttl: timedelta) -> None:
        self._users = UserRepository(db)
        self._sessions = SessionRepository(db)
        self._ttl = session_ttl

    async def register(self, email: str, password: str) -> User:
        password_hash = await passwords.hash_password(password)
        return await self._users.create(normalize_email(email), password_hash)

    async def authenticate(self, email: str, password: str) -> User | None:
        user = await self._users.get_by_email(normalize_email(email))
        ok = await passwords.verify_password(user.password_hash if user else None, password)
        if not (ok and user):
            return None
        if passwords.needs_rehash(user.password_hash):
            await self._users.update_password_hash(user, await passwords.hash_password(password))
        return user

    async def start_session(self, user: User) -> NewSession:
        token = secrets.token_urlsafe(32)  # 256 bits of entropy
        expires_at = datetime.now(UTC) + self._ttl
        await self._sessions.create(user.id, hash_token(token), expires_at)
        return NewSession(token=token, expires_at=expires_at)

    async def resolve(self, token: str) -> ResolvedSession | None:
        now = datetime.now(UTC)
        token_hash = hash_token(token)
        found = await self._sessions.get_active_with_user(token_hash, now)
        if found is None:
            return None
        user_session, user = found
        refreshed = False
        # Sliding expiry, written at most once per half-TTL to avoid a write on every request.
        if user_session.expires_at - now < self._ttl / 2:
            await self._sessions.extend(user_session, now + self._ttl)
            refreshed = True
        return ResolvedSession(user, token_hash, user_session.expires_at, refreshed)

    async def revoke(self, token: str) -> None:
        await self._sessions.revoke(hash_token(token), datetime.now(UTC))
