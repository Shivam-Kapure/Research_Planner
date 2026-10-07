import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.db.repositories.trace import TraceRepository
from app.schemas.trace import TraceEventOut

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}/events")
async def list_run_events(
    run_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    after: int = Query(default=0, ge=0, description="Return events with seq > after"),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[TraceEventOut]:
    """Trace events of a run owned by the current user, in sequence order (polling cursor).

    Ownership is checked through the events' user_id until the runs table exists (Phase 7).
    Another user's run is indistinguishable from a missing one.
    """
    repo = TraceRepository(db)
    if not await repo.owned_run_exists(user.id, run_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found")
    events = await repo.list_for_run(user.id, run_id, after_seq=after, limit=limit)
    return [TraceEventOut.model_validate(e) for e in events]
