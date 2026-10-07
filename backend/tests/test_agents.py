"""Each agent tested on its own: typed input → its own LLM reasoning (scripted) → typed output."""

import json
import uuid

import pytest
from fastapi import FastAPI

from app.agents.analysis import DocumentAnalysisAgent
from app.agents.planner import PlannerAgent
from app.agents.search import LiteratureSearchAgent
from app.agents.synthesis import EvidenceSynthesisAgent
from app.agents.writer import ReviewWriterAgent
from app.llm.types import LLMRequest
from app.orchestration.routing import route_after_replanning, route_after_synthesis
from app.orchestration.validation import SufficiencyRules, compute_coverage, validate_verdict
from app.schemas.contracts import (
    DocumentAnalysis,
    EvidenceItem,
    ReplanningRequest,
    ResearchPlan,
    ResearchRequest,
    SynthesisDecision,
)
from app.schemas.contracts.synthesis import Contradiction
from tests.agent_fakes import (
    ABSTRACT,
    SCOPE_REVISION,
    SEARCH_REVISION,
    ScriptedLLM,
    make_paper,
    make_runtime,
    plan_reply,
    scripts,
    synthesis_reply,
    trace_rows,
    user_json,
)

pytestmark = pytest.mark.anyio

REQUEST = ResearchRequest(
    question="How does sleep deprivation affect memory consolidation?", year_from=2010
)
PLAN = ResearchPlan.model_validate_json(plan_reply())


def evidence(paper_id: uuid.UUID, sq: str, confidence: float = 0.8) -> EvidenceItem:
    return EvidenceItem(
        id=uuid.uuid4(),
        paper_id=paper_id,
        sub_question_id=sq,
        claim="c",
        stance="supports",
        quote="quoted sentence from the paper",
        confidence=confidence,
    )


def analysis(sqs: tuple[str, ...], *, full_text: bool = True) -> DocumentAnalysis:
    pid = uuid.uuid4()
    return DocumentAnalysis(
        paper_id=pid,
        basis="full_text" if full_text else "abstract_only",
        extraction_status="succeeded" if full_text else "degraded",
        failure_reason=None if full_text else "no_oa_pdf",
        evidence=[evidence(pid, sq, 0.8 if full_text else 0.5) for sq in sqs],
    )


# ---------------- Planner ----------------


async def test_planner_produces_a_valid_research_plan(app: FastAPI) -> None:
    llm = ScriptedLLM(scripts([]))
    rt, _ = await make_runtime(app, llm, lambda q: [])
    plan = await PlannerAgent(rt).run(REQUEST, iteration=1)
    assert (
        isinstance(plan, ResearchPlan) and plan.plan_version == 1 and plan.revision_reason is None
    )
    assert plan.year_range is not None and plan.year_range.start == 2010  # request constraint kept
    assert llm.calls == ["ResearchPlan"]


async def test_planner_scope_revision_uses_the_replanning_feedback(app: FastAPI) -> None:
    seen: list[LLMRequest] = []

    def capture(request: LLMRequest) -> str:
        seen.append(request)
        return plan_reply()

    rt, _ = await make_runtime(app, ScriptedLLM(scripts([], ResearchPlan=[capture])), lambda q: [])
    feedback = ReplanningRequest.model_validate(
        {
            "iteration_from": 1,
            "kind": "scope_revision",
            "scope_change": SCOPE_REVISION["scope_change"],
            "reasons": [{"type": "contradiction", "sub_question_id": "sq-1", "detail": "age"}],
        }
    )
    plan = await PlannerAgent(rt).run(REQUEST, iteration=2, previous_plan=PLAN, replanning=feedback)
    assert plan.plan_version == 2 and plan.revision_reason == SCOPE_REVISION["scope_change"]
    context = user_json(seen[0])
    assert context["replanning_request"]["scope_change"] == SCOPE_REVISION["scope_change"]
    assert context["previous_plan"]["plan_version"] == 1


# ---------------- Literature Search ----------------


async def test_search_agent_consumes_a_plan_and_returns_search_results(app: FastAPI) -> None:
    llm = ScriptedLLM(scripts([]))
    rt, source = await make_runtime(
        app,
        llm,
        lambda q: [make_paper("W1", "Sleep loss and recall"), make_paper("W2", "Sleep stages")],
    )
    outcome = await LiteratureSearchAgent(rt).run(
        PLAN,
        iteration=1,
        replanning=None,
        seen_paper_ids=set(),
        previous_queries=[],
        papers_remaining=15,
    )
    results = outcome.results
    assert source.queries[0] == "sleep deprivation memory"
    assert {c.title for c in results.selected} == {"Sleep loss and recall", "Sleep stages"}
    assert all(c.has_oa_pdf and c.sub_question_ids for c in results.selected)
    assert llm.calls == ["QueryPlan", "QueryPlan", "Screening"]  # plan, one refinement, screening
    assert outcome.request.k == 6 and len(outcome.papers) == 2


async def test_search_revision_runs_the_synthesis_directives_and_skips_seen_papers(
    app: FastAPI,
) -> None:
    seen_paper = make_paper("W1", "Already analysed")
    rt, source = await make_runtime(
        app,
        ScriptedLLM(scripts([])),
        lambda q: [seen_paper, make_paper("W9", f"New paper for {q}")],
    )
    revision = ReplanningRequest.model_validate(
        {
            "iteration_from": 1,
            **SEARCH_REVISION,
            "reasons": [{"type": "gap", "sub_question_id": "sq-2", "detail": "missing"}],
        }
    )
    outcome = await LiteratureSearchAgent(rt).run(
        PLAN,
        iteration=2,
        replanning=revision,
        seen_paper_ids={seen_paper.paper_id},
        previous_queries=["sleep deprivation memory"],
        papers_remaining=15,
    )
    assert source.queries[:2] == [
        "sleep stages memory consolidation",
        "sleep deprivation recall meta-analysis",
    ]
    assert seen_paper.paper_id not in {c.paper_id for c in outcome.results.selected}
    assert seen_paper.paper_id in outcome.request.exclude_paper_ids


async def test_search_respects_the_per_run_paper_budget(app: FastAPI) -> None:
    rt, _ = await make_runtime(
        app,
        ScriptedLLM(scripts([])),
        lambda q: [make_paper(f"W{i}", f"Paper {i} {q}") for i in range(10)],
    )
    outcome = await LiteratureSearchAgent(rt).run(
        PLAN,
        iteration=3,
        replanning=None,
        seen_paper_ids=set(),
        previous_queries=[],
        papers_remaining=2,
    )
    assert len(outcome.results.selected) == 2


# ---------------- Document Analysis ----------------


async def test_analysis_extracts_grounded_page_located_evidence(app: FastAPI) -> None:
    llm = ScriptedLLM(scripts([]))
    rt, _ = await make_runtime(app, llm, lambda q: [])
    paper = make_paper("W1", "Sleep loss and recall")
    result = await DocumentAnalysisAgent(rt).analyse(PLAN, paper, iteration=1, parent_id=None)
    assert result.basis == "full_text" and result.extraction_status == "succeeded"
    assert [e.sub_question_id for e in result.evidence] == ["sq-1", "sq-2"]
    assert all(e.location == "p.1" for e in result.evidence)  # quotes found on page 1
    assert result.methods_summary and result.limitations == ["Small sample"]


async def test_analysis_drops_ungrounded_quotes_after_one_retry(app: FastAPI) -> None:
    fabricated = json.dumps(
        {
            "evidence": [
                {
                    "sub_question_id": "sq-1",
                    "claim": "c",
                    "stance": "supports",
                    "quote": "a sentence that is nowhere in the paper at all",
                    "confidence": 0.9,
                }
            ]
        }
    )
    llm = ScriptedLLM(scripts([], PaperExtraction=[fabricated, fabricated]))
    rt, _ = await make_runtime(app, llm, lambda q: [])
    result = await DocumentAnalysisAgent(rt).analyse(
        PLAN, make_paper("W1", "T"), iteration=1, parent_id=None
    )
    assert llm.calls == ["PaperExtraction", "PaperExtraction"]  # grounding retry happened once
    assert result.evidence == [] and result.ungrounded_dropped == 1
    assert result.extraction_status == "degraded"


async def test_analysis_falls_back_to_the_abstract_and_caps_confidence(app: FastAPI) -> None:
    rt, _ = await make_runtime(app, ScriptedLLM(scripts([])), lambda q: [], missing_pdfs={"W3"})
    paper = make_paper("W3", "Age and sleep", abstract=ABSTRACT)
    result = await DocumentAnalysisAgent(rt).analyse(PLAN, paper, iteration=1, parent_id=None)
    assert result.basis == "abstract_only" and result.failure_reason == "download_failed"
    assert result.evidence and all(
        e.confidence <= 0.6 and e.location == "abstract" for e in result.evidence
    )


# ---------------- Evidence Synthesis + deterministic validation ----------------


@pytest.mark.parametrize(
    ("reply", "analyses", "expected"),
    [
        (
            synthesis_reply("sufficient"),
            [analysis(("sq-1", "sq-2")), analysis(("sq-1", "sq-2"))],
            "sufficient",
        ),
        (
            synthesis_reply("insufficient", replanning=SEARCH_REVISION),
            [analysis(("sq-1",))],
            "insufficient",
        ),
        (
            synthesis_reply("contradictory", replanning=SCOPE_REVISION, contradict=True),
            [analysis(("sq-1", "sq-2")), analysis(("sq-1", "sq-2"))],
            "contradictory",
        ),
    ],
    ids=["sufficient", "insufficient", "contradictory"],
)
async def test_synthesis_verdicts(
    app: FastAPI, reply: object, analyses: list[DocumentAnalysis], expected: str
) -> None:
    rt, _ = await make_runtime(app, ScriptedLLM(scripts([reply])), lambda q: [])  # type: ignore[list-item]
    outcome = await EvidenceSynthesisAgent(rt).run(PLAN, analyses, {}, iteration=1, previous=[])
    assert outcome.decision.verdict == expected and outcome.decision.validator_override is None
    if expected == "sufficient":
        assert outcome.replanning is None
    else:
        assert outcome.replanning is not None
        outcome.replanning.check_against(outcome.decision)


async def test_insufficient_produces_a_search_revision_with_directives(app: FastAPI) -> None:
    rt, _ = await make_runtime(
        app,
        ScriptedLLM(scripts([synthesis_reply("insufficient", replanning=SEARCH_REVISION)])),
        lambda q: [],
    )
    outcome = await EvidenceSynthesisAgent(rt).run(
        PLAN, [analysis(("sq-1",))], {}, iteration=1, previous=[]
    )
    request = outcome.replanning
    assert request is not None and request.kind == "search_revision"
    assert {r.sub_question_id for r in request.reasons} == {"sq-1", "sq-2"}  # weak + missing
    assert {d.sub_question_id for d in request.directives} == {"sq-1", "sq-2"}


async def test_contradictory_produces_a_scope_revision(app: FastAPI) -> None:
    rt, _ = await make_runtime(
        app,
        ScriptedLLM(
            scripts([synthesis_reply("contradictory", replanning=SCOPE_REVISION, contradict=True)])
        ),
        lambda q: [],
    )
    outcome = await EvidenceSynthesisAgent(rt).run(
        PLAN, [analysis(("sq-1", "sq-2")), analysis(("sq-1", "sq-2"))], {}, iteration=1, previous=[]
    )
    request = outcome.replanning
    assert request is not None and request.kind == "scope_revision"
    assert request.scope_change == SCOPE_REVISION["scope_change"]
    assert [r.type for r in request.reasons] == ["contradiction"]


async def test_validator_override_is_recorded_and_traced(app: FastAPI) -> None:
    rt, _ = await make_runtime(
        app, ScriptedLLM(scripts([synthesis_reply("sufficient")])), lambda q: []
    )
    outcome = await EvidenceSynthesisAgent(rt).run(
        PLAN, [analysis(("sq-1",))], {}, iteration=1, previous=[]
    )
    decision = outcome.decision
    assert decision.verdict == "insufficient"
    assert (
        decision.validator_override is not None
        and decision.validator_override.original_verdict == "sufficient"
    )
    assert "priority-1 sq-1 is weak" in decision.validator_override.rule_failed
    rows = await trace_rows(app, rt.recorder.run_id)
    validation = [r for r in rows if r["event_type"] == "validation"][0]
    assert (
        validation["status"] == "warning" and "overridden" in validation["validation"]["override"]
    )


async def test_synthesis_ignores_references_to_unknown_evidence(app: FastAPI) -> None:
    bogus = json.dumps(
        {
            "verdict": "contradictory",
            "rationale": "r",
            "contradictions": [
                {
                    "sub_question_id": "sq-1",
                    "claim_a": str(uuid.uuid4()),
                    "claim_b": str(uuid.uuid4()),
                    "explanation": "x",
                }
            ],
        }
    )
    rt, _ = await make_runtime(app, ScriptedLLM(scripts([bogus])), lambda q: [])
    outcome = await EvidenceSynthesisAgent(rt).run(
        PLAN, [analysis(("sq-1", "sq-2")), analysis(("sq-1", "sq-2"))], {}, iteration=1, previous=[]
    )
    assert outcome.decision.contradictions == []
    assert outcome.decision.verdict == "sufficient"  # nothing actually conflicts → override


@pytest.mark.parametrize(
    ("proposed", "sqs", "contradiction", "expected"),
    [
        ("sufficient", [("sq-1", "sq-2"), ("sq-1", "sq-2")], False, "sufficient"),
        ("sufficient", [("sq-1",)], False, "insufficient"),
        ("sufficient", [("sq-1", "sq-2"), ("sq-1", "sq-2")], True, "contradictory"),
        ("contradictory", [("sq-1", "sq-2"), ("sq-1", "sq-2")], False, "sufficient"),
        ("insufficient", [("sq-1", "sq-2"), ("sq-1", "sq-2")], False, "sufficient"),
        ("insufficient", [("sq-2",)], False, "insufficient"),
    ],
)
def test_validator_matrix(
    proposed: str, sqs: list[tuple[str, ...]], contradiction: bool, expected: str
) -> None:
    analyses = [analysis(s) for s in sqs]
    coverage = compute_coverage(PLAN, analyses)
    conflicts = []
    if contradiction:
        a, b = analyses[0].evidence[0], analyses[1].evidence[0]
        conflicts = [
            Contradiction(sub_question_id="sq-1", claim_a=a.id, claim_b=b.id, explanation="x")
        ]
    outcome = validate_verdict(proposed, PLAN, coverage, conflicts, analyses, SufficiencyRules())  # type: ignore[arg-type]
    assert outcome.verdict == expected and outcome.overridden == (proposed != expected)


def test_coverage_counts_distinct_papers_and_full_text() -> None:
    coverage = {
        c.sub_question_id: c
        for c in compute_coverage(
            PLAN,
            [analysis(("sq-1",)), analysis(("sq-1", "sq-1")), analysis(("sq-2",), full_text=False)],
        )
    }
    assert (
        coverage["sq-1"].supporting_papers,
        coverage["sq-1"].full_text_papers,
        coverage["sq-1"].status,
    ) == (2, 2, "covered")
    assert (coverage["sq-2"].supporting_papers, coverage["sq-2"].status) == (1, "weak")


# ---------------- routing ----------------


@pytest.mark.parametrize(
    ("verdict", "iteration", "affordable", "expected"),
    [
        ("sufficient", 1, True, ("writer", "sufficient")),
        ("sufficient", 3, False, ("writer", "sufficient")),
        ("insufficient", 1, True, ("replanning", None)),
        ("contradictory", 2, True, ("replanning", None)),
        ("insufficient", 3, True, ("limit_reached", "iteration_limit")),
        ("contradictory", 3, True, ("limit_reached", "iteration_limit")),
        ("insufficient", 1, False, ("limit_reached", "budget_limit")),
    ],
)
def test_route_after_synthesis(
    verdict: str, iteration: int, affordable: bool, expected: tuple[str, str | None]
) -> None:
    assert route_after_synthesis(verdict, iteration, 3, affordable) == expected  # type: ignore[arg-type]


def test_route_after_replanning() -> None:
    assert route_after_replanning("search_revision") == "search_revision"
    assert route_after_replanning("scope_revision") == "scope_revision"


# ---------------- Review Writer ----------------


async def test_writer_builds_references_from_metadata_and_reports_limits(app: FastAPI) -> None:
    rt, _ = await make_runtime(app, ScriptedLLM(scripts([])), lambda q: [])
    papers = [make_paper(f"W{i}", f"Paper {i}") for i in range(2)]
    by_id = {str(p.paper_id): p for p in papers}
    analyses = [
        DocumentAnalysis(
            paper_id=p.paper_id,
            basis="full_text",
            extraction_status="succeeded",
            evidence=[evidence(p.paper_id, "sq-1")],
        )
        for p in papers
    ]
    decision = SynthesisDecision(
        iteration=3,
        verdict="insufficient",
        coverage=compute_coverage(PLAN, analyses),
        rationale="sq-2 missing",
    )
    review = await ReviewWriterAgent(rt).run(
        REQUEST, PLAN, decision, analyses, by_id, iteration=3, stop_reason="iteration_limit"
    )
    assert review.evidence_status == "limited"
    assert {r.citation_key for r in review.references} == {"P1", "P2"}
    assert {r.title for r in review.references} == {p.title for p in papers}  # from metadata
    assert any("iteration limit (3)" in item for item in review.limitations)
    assert any("sq-2 is missing" in item for item in review.limitations)


async def test_writer_retries_once_on_invented_citations(app: FastAPI) -> None:
    invented = json.dumps(
        {
            "title": "T",
            "abstract": "A",
            "sections": [{"heading": "H", "kind": "body", "body_markdown": "Claim [@X99]."}],
        }
    )
    llm = ScriptedLLM(scripts([], ReviewDraft=[invented, invented]))
    rt, _ = await make_runtime(app, llm, lambda q: [])
    paper = make_paper("W1", "Paper")
    analyses = [
        DocumentAnalysis(
            paper_id=paper.paper_id,
            basis="full_text",
            extraction_status="succeeded",
            evidence=[evidence(paper.paper_id, "sq-1")],
        )
    ]
    with pytest.raises(ValueError, match="unknown citation keys"):
        await ReviewWriterAgent(rt).run(
            REQUEST,
            PLAN,
            None,
            analyses,
            {str(paper.paper_id): paper},
            iteration=1,
            stop_reason=None,
        )
    assert llm.calls == ["ReviewDraft", "ReviewDraft"]


async def test_writer_retry_feeds_back_the_real_problem(app: FastAPI) -> None:
    """Regression from the first live run: an uncited body section must be fixed on retry."""
    seen: list[LLMRequest] = []
    uncited = json.dumps(
        {
            "title": "T",
            "abstract": "A",
            "sections": [
                {"heading": "Effects", "kind": "body", "body_markdown": "Blood pressure fell."}
            ],
        }
    )
    fixed = json.dumps(
        {
            "title": "T",
            "abstract": "A",
            "sections": [
                {
                    "heading": "Effects",
                    "kind": "body",
                    "body_markdown": "Blood pressure fell [@P1].",
                }
            ],
        }
    )

    def reply(request: LLMRequest) -> str:
        seen.append(request)
        return uncited if len(seen) == 1 else fixed

    rt, _ = await make_runtime(app, ScriptedLLM(scripts([], ReviewDraft=[reply])), lambda q: [])
    paper = make_paper("W1", "Paper")
    analyses = [
        DocumentAnalysis(
            paper_id=paper.paper_id,
            basis="full_text",
            extraction_status="succeeded",
            evidence=[evidence(paper.paper_id, "sq-1")],
        )
    ]
    review = await ReviewWriterAgent(rt).run(
        REQUEST, PLAN, None, analyses, {str(paper.paper_id): paper}, iteration=1, stop_reason=None
    )
    assert [r.citation_key for r in review.references] == ["P1"]
    feedback = seen[1].messages[-1].content
    assert "must cite at least one paper" in feedback and "P1" in feedback


def test_grounding_folds_typographic_hyphens_and_spaces() -> None:
    """Regression from the live run: real PDFs use U+2011 (non-breaking hyphen) in '24‑h'."""
    from app.agents.analysis import _norm

    assert _norm("24‑h ambulatory blood pressure") == _norm("24-h ambulatory blood pressure")
    assert _norm("“Systolic − 5 mmHg”") == _norm('"Systolic - 5 mmHg"')
