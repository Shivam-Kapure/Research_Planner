import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status

from app.api.deps import CurrentUser, DbSession
from app.db.models import Run
from app.db.repositories.runs import RunRepository
from app.db.repositories.trace import TraceRepository
from app.schemas.api.runs import (
    TERMINAL_STATUSES,
    AgentOutputOut,
    RunDetail,
    RunError,
    RunPage,
    RunProgress,
    RunResult,
    RunSummary,
)
from app.schemas.contracts import FinalReview, ResearchRequest, SynthesisDecision
from app.schemas.trace import TraceEventOut
from app.services.runs import RunExecutor

router = APIRouter(prefix="/runs", tags=["runs"])

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "No such run for this user"}}


def get_executor(request: Request) -> RunExecutor:
    executor: RunExecutor = request.app.state.run_executor
    return executor


Executor = Annotated[RunExecutor, Depends(get_executor)]


async def owned_run(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Run:
    """Another user's run is indistinguishable from a missing one (404, never 403)."""
    run = await RunRepository(db).get_owned(user.id, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


OwnedRun = Annotated[Run, Depends(owned_run)]


def _detail(run: Run, executor: RunExecutor) -> RunDetail:
    limits = executor.limits
    return RunDetail(
        id=run.id,
        question=run.question,
        status=run.status,
        iteration=run.iteration,
        stop_reason=run.stop_reason,
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
        request=ResearchRequest.model_validate(run.request),
        started_at=run.started_at,
        error=RunError.model_validate(run.error) if run.error else None,
        progress=RunProgress(
            iteration=run.iteration,
            max_iterations=limits.max_iterations,
            llm_calls=run.llm_calls,
            max_llm_calls=limits.max_llm_calls,
            tokens_used=run.tokens_used,
            max_tokens=limits.max_tokens,
        ),
    )


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: {"description": "The user already has a queued or running run"}},
)
async def create_run(
    body: ResearchRequest,
    user: CurrentUser,
    db: DbSession,
    executor: Executor,
    background: BackgroundTasks,
) -> RunDetail:
    """Create a run and start it in the background. Poll GET /api/runs/{id} for progress."""
    runs = RunRepository(db)
    if await runs.has_active(user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A run is already in progress")
    run = await runs.create(user.id, body.question, body.model_dump(mode="json"))
    # Scheduled after the request transaction commits, so the task always sees the run row.
    background.add_task(executor.submit, run.id, user.id, body)
    return _detail(run, executor)


@router.get("")
async def list_runs(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> RunPage:
    """The current user's runs, newest first (metadata only)."""
    rows, total = await RunRepository(db).list_owned(user.id, limit=limit, offset=offset)
    return RunPage(
        items=[RunSummary.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{run_id}", responses=NOT_FOUND)
async def get_run(run: OwnedRun, executor: Executor) -> RunDetail:
    return _detail(run, executor)


@router.post(
    "/{run_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    responses={**NOT_FOUND, 409: {"description": "The run is not active"}},
)
async def cancel_run(run: OwnedRun, executor: Executor) -> RunDetail:
    if run.status in TERMINAL_STATUSES or not executor.cancel(run.id):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Run is not active")
    return _detail(run, executor)


@router.get(
    "/{run_id}/result",
    responses={**NOT_FOUND, 409: {"description": "The run has not finished yet"}},
)
async def get_result(run: OwnedRun, db: DbSession) -> RunResult:
    if run.status not in TERMINAL_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Run is {run.status}")
    repo = RunRepository(db)
    review = await repo.latest_output(run.id, FinalReview.schema_name)
    synthesis = await repo.latest_output(run.id, SynthesisDecision.schema_name)
    return RunResult(
        run_id=run.id,
        status=run.status,
        stop_reason=run.stop_reason,
        review=FinalReview.model_validate(review.payload) if review else None,
        synthesis=SynthesisDecision.model_validate(synthesis.payload) if synthesis else None,
        error=RunError.model_validate(run.error) if run.error else None,
    )


@router.get("/{run_id}/outputs", responses=NOT_FOUND)
async def list_outputs(
    run: OwnedRun,
    db: DbSession,
    agent: str | None = Query(default=None, max_length=16),
    iteration: int | None = Query(default=None, ge=1),
) -> list[AgentOutputOut]:
    """The run's persisted agent outputs (plans, search results, analyses, decisions,
    replanning requests, review), in the order they were produced."""
    outputs = await RunRepository(db).outputs(run.id, agent=agent, iteration=iteration)
    return [AgentOutputOut.model_validate(o) for o in outputs]


@router.get("/{run_id}/events", responses=NOT_FOUND)
async def list_run_events(
    run: OwnedRun,
    user: CurrentUser,
    db: DbSession,
    after: int = Query(default=0, ge=0, description="Return events with seq > after"),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[TraceEventOut]:
    """The run's append-only trace in sequence order; `after` is the polling cursor."""
    events = await TraceRepository(db).list_for_run(user.id, run.id, after_seq=after, limit=limit)
    return [TraceEventOut.model_validate(e) for e in events]
