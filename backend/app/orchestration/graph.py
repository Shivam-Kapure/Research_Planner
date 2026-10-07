"""The ResearchPilot LangGraph (architecture §1).

    START → planner → literature_search → document_analysis → evidence_synthesis
    evidence_synthesis ─ sufficient ─────────────→ review_writer → END
                       ─ limit_reached ──────────→ review_writer
                       ─ insufficient/contradictory → replanning
    replanning ─ search_revision → literature_search
               ─ scope_revision  → planner

Each node runs one agent, traces agent_started/agent_completed (or an error) and a handoff
naming the next node. Conditional edges read the route the node computed and traced, so the
trace always explains why the graph went where it did.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agents.analysis import DocumentAnalysisAgent
from app.agents.planner import PlannerAgent
from app.agents.search import LiteratureSearchAgent
from app.agents.synthesis import EvidenceSynthesisAgent
from app.agents.writer import ReviewWriterAgent
from app.llm.errors import LLMError
from app.llm.structured import summarize_validation_error
from app.orchestration.routing import route_after_replanning, route_after_synthesis
from app.orchestration.runtime import ResearchRuntime
from app.orchestration.state import AgentFailure, ResearchState
from app.schemas.contracts import Contract
from app.schemas.trace import TraceAgent
from app.tools.errors import ToolError

Node = Callable[[ResearchState], Awaitable[dict[str, Any]]]

NODE_AGENT: dict[str, TraceAgent] = {
    "planner": "planner",
    "literature_search": "search",
    "document_analysis": "analysis",
    "evidence_synthesis": "synthesis",
    "replanning": "orchestrator",
    "review_writer": "writer",
}


# State keys whose values are agent contracts to persist (each produced once, by one node).
_OUTPUT_KEYS = (
    "plan_history",
    "search_request",
    "search_history",
    "analysis_history",
    "synthesis_history",
    "replanning_request",
    "final_review",
)


def _contracts_in(update: dict[str, Any]) -> list[Contract]:
    found: list[Contract] = []
    for key in _OUTPUT_KEYS:
        value = update.get(key)
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, Contract):
                found.append(item)
    return found


class AgentNodeError(Exception):
    """A fatal agent failure, already traced. Carries the structured failure."""

    def __init__(self, failure: AgentFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


def build_research_graph(rt: ResearchRuntime) -> Any:
    planner = PlannerAgent(rt)
    search = LiteratureSearchAgent(rt)
    analysis = DocumentAnalysisAgent(rt)
    synthesis = EvidenceSynthesisAgent(rt)
    writer = ReviewWriterAgent(rt)
    recorder = rt.recorder

    async def traced(
        node: str,
        state: ResearchState,
        work: Callable[[uuid.UUID], Awaitable[tuple[dict[str, Any], str, str]]],
    ) -> dict[str, Any]:
        """Run one node: started → work → completed → handoff(next). `work` returns the state
        update, the next node and a one-line summary."""
        agent = NODE_AGENT[node]
        iteration = state.get("iteration", 1)
        if rt.sink:
            await rt.sink.progress(iteration, rt.budget)
        started = await recorder.agent_started(
            agent, iteration=iteration, message=f"{node} started (iteration {iteration})"
        )
        try:
            update, next_node, summary = await work(started.id)
        except (LLMError, ToolError, ValueError) as exc:
            code = getattr(exc, "code", type(exc).__name__)
            message = (
                summarize_validation_error(exc)
                if isinstance(exc, ValidationError)  # never echo model output into errors
                else getattr(exc, "message", str(exc))
            )[:500]
            await recorder.error(
                agent,
                iteration=iteration,
                code=code,
                message=message,
                retryable=False,
                parent_id=started.id,
            )
            await recorder.agent_completed(
                agent,
                iteration=iteration,
                message=f"{node} failed: {code}",
                parent_id=started.id,
                status="failed",
            )
            raise AgentNodeError(
                AgentFailure(node=node, code=code, message=message, iteration=iteration, fatal=True)
            ) from None
        done_iteration = update.get("iteration", iteration)  # replanning starts the next one
        output_ids = []
        if rt.sink:  # persist the agent's contracts now, not at the end of the run
            for output in _contracts_in(update):
                output_ids.append(await rt.sink.save_output(agent, done_iteration, output))
        await recorder.agent_completed(
            agent,
            iteration=done_iteration,
            message=f"{node}: {summary}",
            parent_id=started.id,
            output_ref=output_ids[0] if output_ids else None,
        )
        await recorder.decision(
            agent,
            iteration=update.get("iteration", iteration),
            route=f"{node} → {next_node}",
            rationale=summary,
            to_agent=NODE_AGENT.get(next_node),
            event_type="handoff",
            parent_id=started.id,
        )
        return update

    async def planner_node(state: ResearchState) -> dict[str, Any]:
        async def work(parent: uuid.UUID) -> tuple[dict[str, Any], str, str]:
            previous = state.get("plan")
            replanning = state.get("replanning_request")
            plan = await planner.run(
                state["request"],
                iteration=state.get("iteration", 1),
                previous_plan=previous,
                replanning=replanning
                if replanning and replanning.kind == "scope_revision"
                else None,
                parent_id=parent,
            )
            summary = f"plan v{plan.plan_version} with {len(plan.sub_questions)} sub-questions"
            return {"plan": plan, "plan_history": [plan]}, "literature_search", summary

        return await traced("planner", state, work)

    async def search_node(state: ResearchState) -> dict[str, Any]:
        async def work(parent: uuid.UUID) -> tuple[dict[str, Any], str, str]:
            seen = {uuid.UUID(k) for k in state.get("papers", {})}
            previous_queries = [
                q.query for r in state.get("search_history", []) for q in r.queries_executed
            ]
            analysed = {a.paper_id for a in state.get("analysis_history", [])}
            replanning = state.get("replanning_request")
            outcome = await search.run(
                state["plan"],
                iteration=state.get("iteration", 1),
                # After a scope revision the Planner has already acted on the request.
                replanning=replanning
                if replanning and replanning.kind == "search_revision"
                else None,
                seen_paper_ids=seen,
                previous_queries=previous_queries,
                papers_remaining=rt.limits.max_papers_per_run - len(analysed),
                parent_id=parent,
            )
            r = outcome.results
            summary = (
                f"{len(r.selected)} papers selected from {r.candidates_total} candidates "
                f"({len(r.queries_executed)} source queries)"
            )
            return (
                {
                    "search_request": outcome.request,
                    "search_history": [r],
                    "papers": {str(p.paper_id): p for p in outcome.papers},
                },
                "document_analysis",
                summary,
            )

        return await traced("literature_search", state, work)

    async def analysis_node(state: ResearchState) -> dict[str, Any]:
        async def work(parent: uuid.UUID) -> tuple[dict[str, Any], str, str]:
            outcome = await analysis.run(
                state["plan"],
                list(state["search_history"][-1].selected),
                state.get("papers", {}),
                iteration=state.get("iteration", 1),
                parent_id=parent,
            )
            evidence = sum(len(a.evidence) for a in outcome.analyses)
            summary = (
                f"{len(outcome.analyses)} papers analysed, {evidence} evidence items, "
                f"{len(outcome.failures)} failed"
            )
            return (
                {"analysis_history": outcome.analyses, "errors": outcome.failures},
                "evidence_synthesis",
                summary,
            )

        return await traced("document_analysis", state, work)

    async def synthesis_node(state: ResearchState) -> dict[str, Any]:
        async def work(parent: uuid.UUID) -> tuple[dict[str, Any], str, str]:
            iteration = state.get("iteration", 1)
            outcome = await synthesis.run(
                state["plan"],
                list(state.get("analysis_history", [])),
                state.get("papers", {}),
                iteration=iteration,
                previous=list(state.get("synthesis_history", [])),
                parent_id=parent,
            )
            route, stop = route_after_synthesis(
                outcome.decision.verdict,
                iteration,
                rt.limits.max_iterations,
                rt.budget.can_afford_iteration(),
            )
            await recorder.decision(
                "orchestrator",
                iteration=iteration,
                route=route,
                rationale=(
                    f"verdict={outcome.decision.verdict}, "
                    f"iteration {iteration}/{rt.limits.max_iterations}"
                    + (f", stop_reason={stop}" if stop else "")
                ),
                to_agent="writer" if route != "replanning" else "orchestrator",
                parent_id=parent,
            )
            update: dict[str, Any] = {
                "synthesis_history": [outcome.decision],
                "route": route,
                "stop_reason": stop,
                "replanning_request": outcome.replanning if route == "replanning" else None,
            }
            next_node = "replanning" if route == "replanning" else "review_writer"
            return update, next_node, f"verdict {outcome.decision.verdict} → {route}"

        return await traced("evidence_synthesis", state, work)

    async def replanning_node(state: ResearchState) -> dict[str, Any]:
        async def work(parent: uuid.UUID) -> tuple[dict[str, Any], str, str]:
            request = state["replanning_request"]
            if request is None:  # evidence_synthesis always sets it on this route
                raise ValueError("replanning reached without a replanning request")
            iteration = state.get("iteration", 1) + 1
            kind = route_after_replanning(request.kind)
            await recorder.decision(
                "orchestrator",
                iteration=iteration,
                route=kind,
                rationale="; ".join(
                    f"{r.type} {r.sub_question_id}: {r.detail}" for r in request.reasons
                )[:1000],
                to_agent="search" if kind == "search_revision" else "planner",
                event_type="replan",
                parent_id=parent,
            )
            next_node = "literature_search" if kind == "search_revision" else "planner"
            update = {"iteration": iteration, "replan_history": [request], "route": kind}
            return update, next_node, f"{kind}: starting iteration {iteration}"

        return await traced("replanning", state, work)

    async def writer_node(state: ResearchState) -> dict[str, Any]:
        async def work(parent: uuid.UUID) -> tuple[dict[str, Any], str, str]:
            history = state.get("synthesis_history", [])
            stop = state.get("stop_reason")
            review = await writer.run(
                state["request"],
                state["plan"],
                history[-1] if history else None,
                list(state.get("analysis_history", [])),
                state.get("papers", {}),
                iteration=state.get("iteration", 1),
                stop_reason=stop,
                parent_id=parent,
            )
            status = (
                "completed"
                if review.evidence_status == "sufficient"
                else "completed_with_limitations"
            )
            summary = (
                f"review written ({review.evidence_status}, {len(review.references)} references)"
            )
            return {"final_review": review, "status": status}, END, summary

        return await traced("review_writer", state, work)

    graph = StateGraph(ResearchState)
    graph.add_node("planner", planner_node)
    graph.add_node("literature_search", search_node)
    graph.add_node("document_analysis", analysis_node)
    graph.add_node("evidence_synthesis", synthesis_node)
    graph.add_node("replanning", replanning_node)
    graph.add_node("review_writer", writer_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "literature_search")
    graph.add_edge("literature_search", "document_analysis")
    graph.add_edge("document_analysis", "evidence_synthesis")
    graph.add_conditional_edges(
        "evidence_synthesis",
        lambda s: s["route"],
        {"writer": "review_writer", "limit_reached": "review_writer", "replanning": "replanning"},
    )
    graph.add_conditional_edges(
        "replanning",
        lambda s: s["route"],
        {"search_revision": "literature_search", "scope_revision": "planner"},
    )
    graph.add_edge("review_writer", END)
    return graph.compile()
