from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]
FRONTEND_ORIGIN = "https://app.researchpilot.test"
BASE_URL = "https://testserver"  # https so Secure cookies round-trip like production
PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


class _TestEnv(BaseSettings):
    """TEST_DATABASE_URL from the environment or the untracked root .env, like app settings."""

    model_config = SettingsConfigDict(env_file=BACKEND_DIR.parent / ".env", extra="ignore")

    test_database_url: str | None = None


@pytest.fixture(scope="session")
def test_database_url() -> str:
    raw = _TestEnv().test_database_url
    if not raw:
        pytest.fail(
            "TEST_DATABASE_URL is not set. Point it at a disposable PostgreSQL database "
            "whose name ends in _test (see README)."
        )
    normalised = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    if not (make_url(normalised).database or "").endswith("_test"):
        pytest.fail("Refusing to run: TEST_DATABASE_URL database name must end in _test")
    return normalised


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = database_url
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def migrated_database(test_database_url: str) -> str:
    """Rebuild the test schema from an empty database using the real migrations."""
    cfg = alembic_config(test_database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return test_database_url


@pytest.fixture
def encryption_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def settings(migrated_database: str, encryption_key: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=migrated_database,
        credential_encryption_keys=encryption_key,
        frontend_origin=FRONTEND_ORIGIN,
        session_cookie_secure=True,
    )


async def _truncate(app: FastAPI) -> None:
    async with app.state.database.engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, sessions, user_provider_credentials CASCADE"))


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    await _truncate(application)
    yield application
    await _truncate(application)
    await application.state.database.dispose()


def make_client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with make_client(app) as c:
        yield c


async def register_and_login(
    client: AsyncClient, email: str = "alice@example.com", password: str = PASSWORD
) -> None:
    r = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text


async def execute(app: FastAPI, sql: str, **params: object) -> None:
    async with app.state.database.engine.begin() as conn:
        await conn.execute(text(sql), params)


async def scalar(app: FastAPI, sql: str, **params: object) -> object:
    async with app.state.database.engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()
