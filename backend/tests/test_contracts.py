import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.contracts import (
    CONTRACTS,
    Contract,
    DocumentAnalysis,
    EvidenceSet,
    FinalReview,
    ReplanningRequest,
    ResearchPlan,
    ResearchRequest,
    SearchRequest,
    SearchResults,
    SynthesisDecision,
)
from app.schemas.contracts.synthesis import coverage_status

PAPER_A, PAPER_B = uuid.uuid4(), uuid.uuid4()
EV_A, EV_B = uuid.uuid4(), uuid.uuid4()


def plan_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "plan_version": 1,
        "objective": "Assess how sleep deprivation affects memory consolidation in adults.",
        "sub_questions": [
            {
                "id": "sq-1",
                "text": "Does sleep deprivation impair memory consolidation?",
                "rationale": "Core question",
                "priority": 1,
            },
            {
                "id": "sq-2",
                "text": "Which sleep stages matter most for memory?",
                "rationale": "Mechanism",
                "priority": 2,
            },
        ],
        "search_strategy": "Search OpenAlex and Semantic Scholar for experimental studies.",
        "inclusion_criteria": ["Human adult participants"],
        "exclusion_criteria": ["Animal-only studies"],
        "keywords": ["sleep deprivation", "memory consolidation", "sleep stages"],
        "year_range": {"start": 2010, "end": 2025},
    }
    data.update(overrides)
    return data


def analysis_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "paper_id": str(PAPER_A),
        "basis": "full_text",
        "extraction_status": "succeeded",
        "methods_summary": "Randomised crossover study, n=40.",
        "key_findings": ["Deprivation reduced recall by 20%"],
        "limitations": ["Small sample"],
        "evidence": [
            {
                "id": str(EV_A),
                "paper_id": str(PAPER_A),
                "sub_question_id": "sq-1",
                "claim": "Sleep deprivation reduced next-day recall.",
                "stance": "supports",
                "quote": "recall was 20% lower after a night without sleep",
                "location": "p.4",
                "confidence": 0.8,
            }
        ],
    }
    data.update(overrides)
    return data


def decision_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "iteration": 1,
        "verdict": "insufficient",
        "coverage": [
            {
                "sub_question_id": "sq-1",
                "supporting_papers": 2,
                "full_text_papers": 1,
                "status": "covered",
            },
            {
                "sub_question_id": "sq-2",
                "supporting_papers": 1,
                "full_text_papers": 0,
                "status": "weak",
            },
        ],
        "themes": [{"title": "Recall", "summary": "Recall drops.", "evidence_ids": [str(EV_A)]}],
        "rationale": "sq-2 rests on a single abstract.",
    }
    data.update(overrides)
    return data


def review_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "title": "Sleep and memory",
        "abstract": "A short review.",
        "sections": [
            {"heading": "Introduction", "kind": "introduction", "body_markdown": "Why it matters."},
            {
                "heading": "Findings",
                "body_markdown": "Deprivation impairs recall [@smith2020].",
                "citation_keys": ["smith2020"],
                "evidence_ids": [str(EV_A)],
            },
        ],
        "evidence_status": "sufficient",
        "references": [
            {"citation_key": "smith2020", "paper_id": str(PAPER_A), "title": "Sleep", "year": 2020}
        ],
    }
    data.update(overrides)
    return data


VALID: dict[type[Contract], dict[str, Any]] = {
    ResearchRequest: {"question": "How does sleep deprivation affect memory?", "year_from": 2010},
    ResearchPlan: plan_data(),
    SearchRequest: {
        "iteration": 1,
        "targets": [{"sub_question_id": "sq-1", "queries": ["sleep deprivation memory"]}],
    },
    SearchResults: {
        "iteration": 1,
        "queries_executed": [
            {"source": "openalex", "query": "sleep deprivation memory", "result_count": 40}
        ],
        "candidates_total": 40,
        "duplicates_removed": 3,
        "selected": [
            {
                "paper_id": str(PAPER_A),
                "title": "Sleep loss and recall",
                "year": 2020,
                "sub_question_ids": ["sq-1"],
                "relevance_score": 0.9,
                "reason": "Direct experimental test",
                "has_oa_pdf": True,
            }
        ],
        "rejected_count": 30,
    },
    DocumentAnalysis: analysis_data(),
    EvidenceSet: {
        "iteration": 1,
        "by_sub_question": {"sq-1": [str(EV_A), str(EV_B)]},
        "paper_count": 2,
        "full_text_count": 1,
    },
    SynthesisDecision: decision_data(),
    ReplanningRequest: {
        "iteration_from": 1,
        "kind": "search_revision",
        "reasons": [{"type": "low_quality", "sub_question_id": "sq-2", "detail": "abstract only"}],
        "directives": [{"sub_question_id": "sq-2", "suggested_queries": ["REM sleep memory"]}],
    },
    FinalReview: review_data(),
}


def test_every_contract_is_covered_and_versioned() -> None:
    assert set(VALID) == set(CONTRACTS)
    names = [c.schema_name for c in CONTRACTS]
    assert len(names) == len(set(names))
    for contract, data in VALID.items():
        instance = contract.model_validate(data)
        assert instance.model_dump()["schema_version"] == 1


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda c: c.schema_name)
def test_round_trip_and_deterministic_serialisation(contract: type[Contract]) -> None:
    instance = contract.model_validate(VALID[contract])
    assert contract.model_validate_json(instance.model_dump_json()) == instance
    assert (
        instance.canonical_json()
        == contract.model_validate_json(instance.model_dump_json()).canonical_json()
    )
    assert '"schema_version":1' in instance.canonical_json()


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda c: c.schema_name)
def test_unknown_fields_and_wrong_versions_are_rejected(contract: type[Contract]) -> None:
    with pytest.raises(ValidationError):
        contract.model_validate({**VALID[contract], "api_key": "should-not-be-accepted"})
    with pytest.raises(ValidationError):
        contract.model_validate({**VALID[contract], "schema_version": 2})


def test_contracts_are_immutable() -> None:
    plan = ResearchPlan.model_validate(plan_data())
    with pytest.raises(ValidationError):
        plan.objective = "changed"  # type: ignore[misc]


def test_canonical_json_ignores_dict_insertion_order() -> None:
    a = EvidenceSet.model_validate(
        {
            "iteration": 1,
            "by_sub_question": {"sq-1": [], "sq-2": []},
            "paper_count": 0,
            "full_text_count": 0,
        }
    )
    b = EvidenceSet.model_validate(
        {
            "iteration": 1,
            "by_sub_question": {"sq-2": [], "sq-1": []},
            "paper_count": 0,
            "full_text_count": 0,
        }
    )
    assert a.canonical_json() == b.canonical_json()


INVALID: list[tuple[type[Contract], dict[str, Any]]] = [
    (ResearchRequest, {"question": "too short"}),
    (
        ResearchRequest,
        {"question": "How does sleep affect memory?", "year_from": 2020, "year_to": 2010},
    ),
    (ResearchRequest, {"question": "How does sleep affect memory?", "max_iterations": 4}),
    (ResearchPlan, plan_data(sub_questions=plan_data()["sub_questions"][:1])),
    (
        ResearchPlan,
        plan_data(sub_questions=[plan_data()["sub_questions"][0], plan_data()["sub_questions"][0]]),
    ),
    (ResearchPlan, plan_data(plan_version=2)),  # revision without a reason
    (ResearchPlan, plan_data(keywords=["oncology", "tumour", "chemotherapy"])),  # off-topic
    (ResearchPlan, plan_data(year_range={"start": 2025, "end": 2010})),
    (
        ResearchPlan,
        plan_data(sub_questions=[{**sq, "priority": 2} for sq in plan_data()["sub_questions"]]),
    ),
    (
        ResearchPlan,
        plan_data(
            sub_questions=[
                {**plan_data()["sub_questions"][0], "id": "q1"},
                plan_data()["sub_questions"][1],
            ]
        ),
    ),
    (SearchRequest, {"iteration": 1, "targets": []}),
    (
        SearchRequest,
        {"iteration": 1, "targets": [{"sub_question_id": "sq-1", "queries": ["x"]}], "k": 7},
    ),
    (SearchResults, {**VALID[SearchResults], "candidates_total": 5}),
    (SearchResults, {**VALID[SearchResults], "degraded_sources": ["google_scholar"]}),
    (SearchResults, {**VALID[SearchResults], "selected": VALID[SearchResults]["selected"] * 2}),
    (DocumentAnalysis, analysis_data(paper_id=str(PAPER_B))),  # evidence from another paper
    (
        DocumentAnalysis,
        analysis_data(basis="abstract_only", failure_reason="no_oa_pdf"),
    ),  # 0.8 > 0.6
    (DocumentAnalysis, analysis_data(basis="metadata_only", failure_reason="no_abstract")),
    (DocumentAnalysis, analysis_data(basis="abstract_only", evidence=[])),  # no failure_reason
    (
        DocumentAnalysis,
        analysis_data(extraction_status="failed", failure_reason="extraction_error"),
    ),
    (EvidenceSet, {**VALID[EvidenceSet], "full_text_count": 3}),
    (EvidenceSet, {**VALID[EvidenceSet], "by_sub_question": {"question-1": []}}),
    (SynthesisDecision, decision_data(verdict="maybe")),
    (
        SynthesisDecision,
        decision_data(
            coverage=[
                {
                    "sub_question_id": "sq-1",
                    "supporting_papers": 1,
                    "full_text_papers": 0,
                    "status": "covered",
                }
            ]
        ),
    ),
    (
        SynthesisDecision,
        decision_data(
            verdict="sufficient",
            coverage=[
                {
                    "sub_question_id": "sq-1",
                    "supporting_papers": 0,
                    "full_text_papers": 0,
                    "status": "missing",
                }
            ],
        ),
    ),
    (SynthesisDecision, decision_data(verdict="contradictory")),  # no unresolved contradiction
    (
        SynthesisDecision,
        decision_data(
            coverage=[
                {
                    "sub_question_id": "sq-1",
                    "supporting_papers": 2,
                    "full_text_papers": 1,
                    "status": "covered",
                }
            ]
        ),
    ),  # insufficient while everything is covered
    (
        SynthesisDecision,
        decision_data(
            verdict="contradictory",
            contradictions=[
                {
                    "sub_question_id": "sq-1",
                    "claim_a": str(EV_A),
                    "claim_b": str(EV_A),
                    "explanation": "same item",
                }
            ],
        ),
    ),
    (ReplanningRequest, {**VALID[ReplanningRequest], "directives": []}),
    (ReplanningRequest, {**VALID[ReplanningRequest], "kind": "scope_revision"}),  # no scope_change
    (ReplanningRequest, {**VALID[ReplanningRequest], "kind": "start_over"}),
    (FinalReview, review_data(references=[])),  # citation without a reference
    (
        FinalReview,
        review_data(
            sections=[
                {"heading": "Findings", "body_markdown": "Uncited claim.", "citation_keys": []}
            ]
        ),
    ),
    (
        FinalReview,
        review_data(
            sections=[
                {
                    "heading": "Findings",
                    "body_markdown": "Claim [@smith2020].",
                    "citation_keys": ["other"],
                }
            ]
        ),
    ),
    (FinalReview, review_data(evidence_status="limited")),  # limitations missing
]


@pytest.mark.parametrize(("contract", "data"), INVALID, ids=lambda v: getattr(v, "schema_name", ""))
def test_malformed_contracts_are_rejected(contract: type[Contract], data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        contract.model_validate(data)


def test_contradictory_and_scope_revision_paths_are_representable() -> None:
    decision = SynthesisDecision.model_validate(
        decision_data(
            verdict="contradictory",
            contradictions=[
                {
                    "sub_question_id": "sq-1",
                    "claim_a": str(EV_A),
                    "claim_b": str(EV_B),
                    "explanation": "Opposite effects in older adults",
                }
            ],
        )
    )
    request = ReplanningRequest.model_validate(
        {
            "iteration_from": 1,
            "kind": "scope_revision",
            "reasons": [
                {"type": "contradiction", "sub_question_id": "sq-1", "detail": "age moderates"}
            ],
            "scope_change": "Split sq-1 by age group.",
        }
    )
    request.check_against(decision)  # backed by the unresolved contradiction


def test_replanning_request_must_be_backed_by_the_decision() -> None:
    decision = SynthesisDecision.model_validate(decision_data())
    ReplanningRequest.model_validate(VALID[ReplanningRequest]).check_against(decision)

    unsupported = ReplanningRequest.model_validate(
        {
            **VALID[ReplanningRequest],
            "reasons": [{"type": "gap", "sub_question_id": "sq-1", "detail": "already covered"}],
        }
    )
    with pytest.raises(ValueError, match="not supported"):
        unsupported.check_against(decision)
    with pytest.raises(ValueError, match="iteration"):
        ReplanningRequest.model_validate(
            {**VALID[ReplanningRequest], "iteration_from": 2}
        ).check_against(decision)


@pytest.mark.parametrize(
    ("supporting", "full_text", "expected"),
    [(0, 0, "missing"), (1, 1, "weak"), (2, 0, "weak"), (2, 1, "covered"), (5, 3, "covered")],
)
def test_coverage_rule(supporting: int, full_text: int, expected: str) -> None:
    assert coverage_status(supporting, full_text) == expected
