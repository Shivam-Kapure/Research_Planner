from fastapi import APIRouter
from pydantic import BaseModel

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


@router.get("/readyz")
async def readyz() -> ReadinessResponse:
    """Readiness: dependencies are reachable. The database check is added in Phase 3."""
    checks: dict[str, str] = {}
    return ReadinessResponse(status="ready", checks=checks)
