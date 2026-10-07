import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import auth, credentials, health, runs
from app.config import Settings, get_settings
from app.core.security import origin_guard, validation_error_handler
from app.db.session import Database
from app.llm.factory import build_gateway_for_user, rate_limiters_from
from app.llm.gateway import LLMGateway
from app.services.credential_crypto import CredentialCipher
from app.services.runs import RunExecutor
from app.tools.documents.pdf import SafePdfFetcher
from app.tools.literature.search import build_literature_service

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """App factory. Run with `uvicorn --factory app.main:create_app`.

    Startup needs only the database URL and the encryption key; no LLM key is required.
    """
    settings = settings or get_settings()
    # Fail at startup, with a clear message, if the encryption keys are missing or invalid.
    cipher = CredentialCipher(settings.credential_encryption_keys.get_secret_value())
    database = Database(settings.database_url.get_secret_value())
    # One shared HTTP client for LLM providers, literature APIs and PDF downloads.
    http_client = httpx2.AsyncClient(timeout=30.0)
    limiters = rate_limiters_from(settings)  # per (provider, user) pacing shared by all runs

    async def gateway_for(session: AsyncSession, user_id: uuid.UUID) -> LLMGateway:
        return await build_gateway_for_user(
            session,
            user_id,
            cipher=cipher,
            settings=settings,
            http_client=http_client,
            limiters=limiters,
        )

    executor = RunExecutor(
        database.sessionmaker,
        gateway_factory=gateway_for,
        literature=build_literature_service(settings, http_client),
        fetcher=SafePdfFetcher(http_client),
        max_concurrent=settings.max_concurrent_runs,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            swept = await application.state.run_executor.sweep_interrupted()
            if swept:
                logger.warning("marked %d interrupted run(s) as failed", swept)
        except Exception as exc:  # noqa: BLE001 - the API must still start (readyz reports DB)
            logger.warning("interrupted-run sweep skipped: %s", type(exc).__name__)
        yield
        await application.state.run_executor.shutdown()
        await http_client.aclose()
        await database.dispose()

    app = FastAPI(title="ResearchPilot API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.cipher = cipher
    app.state.http_client = http_client
    app.state.run_executor = executor

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.middleware("http")(origin_guard({settings.frontend_origin}))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Root health endpoints serve the hosting platform; /api/* is what the frontend
    # reaches through its same-origin rewrite proxy (including the cold-start probe).
    app.include_router(health.router)
    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(credentials.router)
    api.include_router(runs.router)
    app.include_router(api)
    return app
