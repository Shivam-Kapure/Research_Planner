"""End-to-end execution of the REAL LangGraph with the five real agents, the Phase 5 tools
(real search service, dedupe, ranking, safe PDF fetcher, pypdf extraction over a local fixture)
and the real trace recorder. Only the LLM provider and literature source are scripted."""

from typing import Any

import pytest
from fastapi import FastAPI

from app.llm.gateway import LLMGateway
from app.orchestration.graph import build_research_graph
from app.orchestration.runner import run_research
from app.schemas.contracts import ResearchRequest
from tests.agent_fakes import (
    ABSTRACT,
    SCOPE_REVISION,
    SEARCH_REVISION,
    ScriptedLLM,
    make_paper,
    make_runtime,
    plan_reply,
    revised_plan_reply,
    scripts,
    synthesis_reply,
    trace_rows,
)

pytestmark = pytest.mark.anyio

REQUEST = ResearchRequest(
    question="How does sleep deprivation affect memory consolidation in adults?"
)


def started(rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    return [(r["agent"], r["iteration"]) for r in rows if r["event_type"] == "agent_started"]


def events(rows: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [r for r in rows if r["event_type"] == event_type]


def catalog_search_revision(query: str) -> list[Any]:
    if query == "sleep deprivation memory":
        return [make_paper("W1", "Sleep loss and recall in young adults")]
    if any(word in query for word in ("stages", "meta-analysis", "slow wave")):
        return [
            make_paper("W2", "Sleep stages and overnight memory retention"),
            make_paper("W3", "Age moderates the effect of sleep loss on memory", abstract=ABSTRACT),
        ]
    return []


async def test_graph_compiles_with_the_agent_nodes(app: FastAPI) -> None:
    rt, _ = await make_runtime(app, ScriptedLLM({}), lambda q: [])
    nodes = set(build_research_graph(rt).get_graph().nodes)
    assert {
        "planner",
        "literature_search",
        "document_analysis",
        "evidence_synthesis",
        "replanning",
        "review_writer",
    } <= nodes


async def test_sufficient_evidence_goes_straight_to_the_writer(app: FastAPI) -> None:
    llm = ScriptedLLM(scripts([synthesis_reply("sufficient")]))
    rt, _ = await make_runtime(
        app,
        llm,
        lambda q: [
            make_paper("W1", "Sleep loss and recall"),
            make_paper("W2", "Sleep stages and memory"),
        ],
    )
    state = await run_research(rt, REQUEST)

    assert state["status"] == "completed" and state["stop_reason"] == "sufficient"
    rows = await trace_rows(app, rt.recorder.run_id)
    assert [a for a, _ in started(rows)] == ["planner", "search", "analysis", "synthesis", "writer"]
    assert (
        state["final_review"] is not None and state["final_review"].evidence_status == "sufficient"
    )


async def test_adaptive_loop_insufficient_search_revision_then_sufficient(app: FastAPI) -> None:
    """CA3 acceptance path: Planner → Search → Analysis → Synthesis(INSUFFICIENT) →
    Replanning(SEARCH_REVISION) → Search → Analysis → Synthesis(SUFFICIENT) → Writer."""
    llm = ScriptedLLM(
        scripts(
            [
                synthesis_reply("insufficient", replanning=SEARCH_REVISION),
                synthesis_reply("sufficient"),
            ]
        )
    )
    rt, source = await make_runtime(app, llm, catalog_search_revision, missing_pdfs={"W3"})
    state = await run_research(rt, REQUEST)
    rows = await trace_rows(app, rt.recorder.run_id)

    # --- the graph really looped: agent sequence and iterations from the trace
    assert started(rows) == [
        ("planner", 1),
        ("search", 1),
        ("analysis", 1),
        ("synthesis", 1),
        ("orchestrator", 1),  # replanning node
        ("search", 2),
        ("analysis", 2),
        ("synthesis", 2),
        ("writer", 2),
    ]
    # --- synthesis verdicts, routing decision and the replanning request are all traced
    verdicts = [
        r["decision"]["route"] for r in events(rows, "decision") if r["agent"] == "synthesis"
    ]
    assert verdicts == ["insufficient", "sufficient"]
    routes = [
        r["decision"]["route"] for r in events(rows, "decision") if r["agent"] == "orchestrator"
    ]
    assert routes == ["replanning", "writer"]
    replans = events(rows, "replan")
    assert [
        (r["iteration"], r["decision"]["route"], r["decision"]["to_agent"]) for r in replans
    ] == [(2, "search_revision", "search")]
    handoffs = [r["decision"]["route"] for r in events(rows, "handoff")]
    assert handoffs == [
        "planner → literature_search",
        "literature_search → document_analysis",
        "document_analysis → evidence_synthesis",
        "evidence_synthesis → replanning",
        "replanning → literature_search",
        "literature_search → document_analysis",
        "document_analysis → evidence_synthesis",
        "evidence_synthesis → review_writer",
        "review_writer → __end__",
    ]
    completed = events(rows, "agent_completed")
    assert len(completed) == 9 and all(r["status"] == "ok" for r in completed)

    # --- the search revision was meaningful: the synthesis directives were searched
    assert "sleep stages memory consolidation" in source.queries
    assert "sleep deprivation recall meta-analysis" in source.queries
    second_search = state["search_history"][1]
    assert {str(p.paper_id) for p in second_search.selected}.isdisjoint(
        {str(p.paper_id) for p in state["search_history"][0].selected}
    )

    # --- information flowed between agents through typed state
    assert len(state["synthesis_history"]) == 2 and len(state["replan_history"]) == 1
    assert state["replan_history"][0].kind == "search_revision"
    assert state["synthesis_history"][1].verdict == "sufficient"
    assert {c.status for c in state["synthesis_history"][1].coverage} == {"covered"}
    review = state["final_review"]
    assert review is not None and {r.citation_key for r in review.references} == {"P1", "P2", "P3"}
    assert state["status"] == "completed" and state["iteration"] == 2

    # --- one PDF was missing (404) → that paper was analysed from its abstract, run continued
    bases = {a.basis for a in state["analysis_history"]}
    assert bases == {"full_text", "abstract_only"}


async def test_contradictory_evidence_triggers_scope_revision_back_to_the_planner(
    app: FastAPI,
) -> None:
    llm = ScriptedLLM(
        scripts(
            [
                synthesis_reply("contradictory", replanning=SCOPE_REVISION, contradict=True),
                synthesis_reply("sufficient"),
            ],
            ResearchPlan=[plan_reply, revised_plan_reply],
        )
    )

    def catalog(query: str) -> list[Any]:
        if query == "older adults sleep memory":
            return [make_paper("W4", "Sleep loss in older adults and recall")]
        return [
            make_paper("W1", "Sleep loss and recall"),
            make_paper("W2", "Sleep stages and memory"),
        ]

    rt, _ = await make_runtime(app, llm, catalog)
    state = await run_research(rt, REQUEST)
    rows = await trace_rows(app, rt.recorder.run_id)

    assert [a for a, _ in started(rows)] == [
        "planner",
        "search",
        "analysis",
        "synthesis",
        "orchestrator",
        "planner",
        "search",
        "analysis",
        "synthesis",
        "writer",
    ]
    assert [r["decision"]["route"] for r in events(rows, "replan")] == ["scope_revision"]
    first = state["synthesis_history"][0]
    assert first.verdict == "contradictory" and first.contradictions[0].resolved is False
    # the Planner revised the plan using the replanning feedback
    assert [p.plan_version for p in state["plan_history"]] == [1, 2]
    revised = state["plan_history"][1]
    assert revised.revision_reason == SCOPE_REVISION["scope_change"]
    assert "older adults" in revised.sub_questions[0].text
    assert state["status"] == "completed"


async def test_iteration_limit_stops_the_loop_and_writer_reports_limitations(app: FastAPI) -> None:
    llm = ScriptedLLM(scripts([synthesis_reply("insufficient", replanning=SEARCH_REVISION)]))
    counter = iter(range(100))
    # Every query finds one new abstract-only paper: never enough full text to be sufficient.
    rt, _ = await make_runtime(
        app,
        llm,
        lambda q: [
            make_paper(
                f"W{100 + next(counter)}", f"Abstract-only study {q}", pdf=False, abstract=ABSTRACT
            )
        ],
    )
    state = await run_research(rt, REQUEST)
    rows = await trace_rows(app, rt.recorder.run_id)

    agents = [a for a, _ in started(rows)]
    assert (
        agents.count("synthesis") == 3 and agents.count("orchestrator") == 2
    )  # 3 iterations, 2 replans
    assert agents[-1] == "writer" and state["iteration"] == 3
    routes = [
        r["decision"]["route"] for r in events(rows, "decision") if r["agent"] == "orchestrator"
    ]
    assert routes == ["replanning", "replanning", "limit_reached"]
    assert state["stop_reason"] == "iteration_limit"
    review = state["final_review"]
    assert review is not None and review.evidence_status == "limited"
    assert any("iteration limit (3)" in limitation for limitation in review.limitations)
    assert state["status"] == "completed_with_limitations"
    run_completed = events(rows, "run_completed")[0]
    assert "iteration_limit" in run_completed["message"]


async def test_validator_overrides_an_unsupported_sufficient_verdict(app: FastAPI) -> None:
    """The LLM claims 'sufficient' after one paper; the deterministic rules disagree, the
    override is traced, and the graph keeps researching instead of writing too early."""
    llm = ScriptedLLM(scripts([synthesis_reply("sufficient"), synthesis_reply("sufficient")]))
    rt, _ = await make_runtime(app, llm, catalog_search_revision)
    state = await run_research(rt, REQUEST)
    rows = await trace_rows(app, rt.recorder.run_id)

    first = state["synthesis_history"][0]
    assert first.verdict == "insufficient"
    assert (
        first.validator_override is not None
        and first.validator_override.original_verdict == "sufficient"
    )
    overrides = [r for r in events(rows, "validation") if r["validation"]["override"]]
    assert overrides and "overridden to 'insufficient'" in overrides[0]["validation"]["override"]
    # The replanning request was built deterministically from the coverage gaps.
    assert state["replan_history"][0].kind == "search_revision"
    assert state["synthesis_history"][-1].verdict == "sufficient" and state["status"] == "completed"


async def test_one_failing_paper_does_not_stop_the_run(app: FastAPI) -> None:
    llm = ScriptedLLM(scripts([synthesis_reply("sufficient")]))
    rt, _ = await make_runtime(
        app,
        llm,
        lambda q: [
            make_paper("W1", "Sleep loss and recall"),
            make_paper("W2", "Sleep stages and memory"),
            make_paper("W5", "Broken extraction study"),  # LLM returns invalid JSON twice
            make_paper("W6", "Paywalled study without abstract", pdf=False),
        ],
    )
    state = await run_research(rt, REQUEST)
    rows = await trace_rows(app, rt.recorder.run_id)

    assert state["status"] == "completed"
    failures = state["errors"]
    assert [(f.node, f.code) for f in failures] == [
        ("document_analysis", "structured_output_invalid")
    ]
    unavailable = [a for a in state["analysis_history"] if a.basis == "metadata_only"]
    assert len(unavailable) == 1 and unavailable[0].failure_reason == "no_oa_pdf"
    assert any(
        r["agent"] == "analysis" and r["error"]["code"] == "structured_output_invalid"
        for r in events(rows, "error")
    )


async def test_fatal_error_is_structured_and_traced(app: FastAPI) -> None:
    rt, _ = await make_runtime(
        app, ScriptedLLM({}), lambda q: [], gateway=LLMGateway({}, {"groq": ["m"]})
    )
    state = await run_research(rt, REQUEST)
    rows = await trace_rows(app, rt.recorder.run_id)

    assert state["status"] == "failed"
    assert (
        state["errors"][-1].code == "no_provider_configured"
        and state["errors"][-1].node == "planner"
    )
    assert [r["event_type"] for r in rows] == [
        "run_started",
        "agent_started",
        "error",
        "agent_completed",
        "run_completed",
    ]
    assert rows[-1]["status"] == "failed"


async def test_trace_sequence_is_gap_free_and_parented(app: FastAPI) -> None:
    llm = ScriptedLLM(scripts([synthesis_reply("sufficient")]))
    rt, _ = await make_runtime(app, llm, lambda q: [make_paper("W1", "A"), make_paper("W2", "B")])
    await run_research(rt, REQUEST)
    rows = await trace_rows(app, rt.recorder.run_id)

    assert [r["seq"] for r in rows] == list(range(1, len(rows) + 1))
    assert rows[0]["event_type"] == "run_started" and rows[-1]["event_type"] == "run_completed"
    started_ids = {r["id"] for r in events(rows, "agent_started")}
    for r in rows:
        if r["event_type"] in ("llm_call", "tool_call", "validation", "agent_completed", "handoff"):
            assert r["parent_id"] in started_ids, r
    assert all(r["llm"]["model"] == "scripted-model" for r in events(rows, "llm_call"))
    assert {r["tool"]["name"] for r in events(rows, "tool_call")} == {
        "literature_search",
        "retrieve_document",
    }
