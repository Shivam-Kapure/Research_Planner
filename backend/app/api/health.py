import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import get_database
from app.db.session import Database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]


@router.get("/healthz")
async def healthz() -> HealthResponse:
    """Liveness: the process is up. Never touches external dependencies."""
    return HealthResponse(status="ok")


@router.get("/readyz", responses={503: {"model": ReadinessResponse}})
async def readyz(database: Database = Depends(get_database)) -> JSONResponse:  # noqa: B008
    """Readiness: PostgreSQL is reachable. Failure details are logged, never returned."""
    try:
        await database.ping()
    except Exception as exc:
        # Exception type only: driver messages can contain hostnames or usernames.
        logger.warning("Readiness check failed: database unreachable (%s)", type(exc).__name__)
        body = ReadinessResponse(status="not_ready", checks={"database": "unavailable"})
        return JSONResponse(body.model_dump(), status_code=503)
    body = ReadinessResponse(status="ready", checks={"database": "ok"})
    return JSONResponse(body.model_dump())
