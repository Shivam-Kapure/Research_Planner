from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User
from app.db.session import Database
from app.services.auth import AuthService
from app.services.credential_crypto import CredentialCipher
from app.services.credentials import CredentialService


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


async def get_db(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    """One transaction per request: committed on success, rolled back on any error."""
    async with database.sessionmaker() as session, session.begin():
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
# scope="function": commit before the response is sent, so a failed commit is a 500,
# never a success response for data that was not saved.
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]


def get_auth_service(db: DbSession, settings: SettingsDep) -> AuthService:
    return AuthService(db, timedelta(days=settings.session_ttl_days))


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_credential_service(db: DbSession, request: Request) -> CredentialService:
    cipher: CredentialCipher = request.app.state.cipher
    return CredentialService(db, cipher)


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_days * 86400,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


async def get_current_user(
    request: Request, response: Response, auth: AuthServiceDep, settings: SettingsDep
) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    resolved = await auth.resolve(token) if token else None
    if resolved is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if resolved.refreshed and token:
        set_session_cookie(response, settings, token)
    return resolved.user


CurrentUser = Annotated[User, Depends(get_current_user)]
CredentialServiceDep = Annotated[CredentialService, Depends(get_credential_service)]
