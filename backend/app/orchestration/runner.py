"""Entry point for one research run: traces run_started/run_completed around the graph and
turns failures into a structured final state. (The Runs API that calls this is Phase 7.)"""

import asyncio
from typing import Any

from langgraph.errors import GraphRecursionError

from app.llm.errors import LLMError
from app.orchestration.graph import AgentNodeError, build_research_graph
from app.orchestration.runtime import ResearchRuntime
from app.orchestration.state import AgentFailure, ResearchState
from app.schemas.contracts import ResearchRequest


async def run_research(rt: ResearchRuntime, request: ResearchRequest) -> ResearchState:
    """Execute the graph to completion (bounded by iterations, recursion limit and a wall-clock
    timeout). Always returns the last state reached; never raises for agent/tool failures."""
    limits = rt.limits
    await rt.recorder.record(
        {
            "agent": "orchestrator",
            "event_type": "run_started",
            "iteration": 1,
            "message": f"run started (max {limits.max_iterations} iterations)",
        }
    )
    graph = build_research_graph(rt)
    state: dict[str, Any] = {"request": request, "iteration": 1, "status": "running", "papers": {}}
    failure: AgentFailure | None = None
    try:
        async with asyncio.timeout(limits.run_timeout_s):
            async for snapshot in graph.astream(
                state, config={"recursion_limit": limits.recursion_limit}, stream_mode="values"
            ):
                state = snapshot
    except AgentNodeError as exc:
        failure = exc.failure
    except LLMError as exc:  # raised outside an agent node (e.g. no provider configured)
        failure = AgentFailure(
            node="run",
            code=exc.code,
            message=exc.message,
            iteration=state.get("iteration", 1),
            fatal=True,
        )
    except GraphRecursionError:
        failure = AgentFailure(
            node="run",
            code="recursion_limit",
            message="graph step limit reached",
            iteration=state.get("iteration", 1),
            fatal=True,
        )
    except TimeoutError:
        failure = AgentFailure(
            node="run",
            code="timeout",
            message="run exceeded its time limit",
            iteration=state.get("iteration", 1),
            fatal=True,
        )

    if failure is not None:
        # Partial when synthesis results exist (themes can still be shown), failed otherwise.
        status = "partial" if state.get("synthesis_history") else "failed"
        state = {**state, "status": status, "errors": [*state.get("errors", []), failure]}
        if failure.node == "run":
            await rt.recorder.error(
                "orchestrator",
                iteration=failure.iteration,
                code=failure.code,
                message=failure.message,
                retryable=False,
            )
    await rt.recorder.record(
        {
            "agent": "orchestrator",
            "event_type": "run_completed",
            "iteration": state.get("iteration", 1),
            "status": "ok" if state.get("status", "").startswith("completed") else "failed",
            "message": f"run {state.get('status')} after {state.get('iteration', 1)} iteration(s)"
            + (f", stop_reason={state.get('stop_reason')}" if state.get("stop_reason") else ""),
        }
    )
    return state  # type: ignore[return-value]
