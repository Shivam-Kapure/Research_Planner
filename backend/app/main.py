from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, credentials, health
from app.config import Settings, get_settings
from app.core.security import origin_guard, validation_error_handler
from app.db.session import Database
from app.services.credential_crypto import CredentialCipher


def create_app(settings: Settings | None = None) -> FastAPI:
    """App factory. Run with `uvicorn --factory app.main:create_app`."""
    settings = settings or get_settings()
    # Fail at startup, with a clear message, if the encryption keys are missing or invalid.
    cipher = CredentialCipher(settings.credential_encryption_keys.get_secret_value())
    database = Database(settings.database_url.get_secret_value())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await database.dispose()

    app = FastAPI(title="ResearchPilot API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.cipher = cipher

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
    app.include_router(api)
    return app
