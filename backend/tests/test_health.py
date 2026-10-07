from collections.abc import AsyncIterator

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx2 import AsyncClient

from app.config import Settings
from app.main import create_app
from tests.conftest import make_client

pytestmark = pytest.mark.anyio

# Nothing listens on port 1, so connecting fails fast. The password is a sentinel that
# must never appear in a response.
UNREACHABLE_DB = "postgresql+asyncpg://rp_user:sentinel-db-password@127.0.0.1:1/unreachable_test"


@pytest.fixture
async def app_without_db() -> AsyncIterator[FastAPI]:
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=UNREACHABLE_DB,
            credential_encryption_keys=Fernet.generate_key().decode(),
        )
    )
    yield app
    await app.state.database.dispose()


async def test_healthz_works_without_database(app_without_db: FastAPI) -> None:
    async with make_client(app_without_db) as client:
        for path in ("/healthz", "/api/healthz"):
            response = await client.get(path)
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}


async def test_readyz_succeeds_with_database(client: AsyncClient) -> None:
    for path in ("/readyz", "/api/readyz"):
        response = await client.get(path)
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


async def test_readyz_fails_safely_when_database_unavailable(app_without_db: FastAPI) -> None:
    async with make_client(app_without_db) as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": "unavailable"}}
    for leaked in ("sentinel-db-password", "rp_user", "127.0.0.1", "postgresql"):
        assert leaked not in response.text


async def test_cors_allows_only_configured_frontend_origin(client: AsyncClient) -> None:
    allowed = await client.get("/healthz", headers={"Origin": "https://app.researchpilot.test"})
    denied = await client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert allowed.headers.get("access-control-allow-origin") == "https://app.researchpilot.test"
    assert "access-control-allow-origin" not in denied.headers
