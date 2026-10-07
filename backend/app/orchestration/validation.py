"""Deterministic sufficiency validation (architecture §1, §12).

The Evidence Synthesis Agent's LLM *proposes* a verdict; these explicit rules decide whether it
stands. An override keeps the original verdict on the decision (`validator_override`) and is
traced, so it is never hidden.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.schemas.contracts import DocumentAnalysis, ResearchPlan
from app.schemas.contracts.synthesis import Contradiction, Coverage, Verdict, coverage_status


@dataclass(frozen=True)
class SufficiencyRules:
    min_papers_with_evidence: int = 2
    min_evidence_items: int = 3
    require_priority1_covered: bool = True
    forbid_missing_sub_questions: bool = True
    forbid_unresolved_priority1_contradictions: bool = True


@dataclass(frozen=True)
class ValidationOutcome:
    verdict: Verdict
    failed_rules: tuple[str, ...]
    overridden: bool
    original_verdict: Verdict


def compute_coverage(plan: ResearchPlan, analyses: Sequence[DocumentAnalysis]) -> list[Coverage]:
    """Per sub-question: distinct papers with evidence, and how many of them were full text."""
    coverage = []
    for sq in plan.sub_questions:
        papers = {
            a.paper_id for a in analyses if any(e.sub_question_id == sq.id for e in a.evidence)
        }
        full_text = {
            a.paper_id
            for a in analyses
            if a.basis == "full_text" and any(e.sub_question_id == sq.id for e in a.evidence)
        }
        coverage.append(
            Coverage(
                sub_question_id=sq.id,
                supporting_papers=len(papers),
                full_text_papers=len(full_text),
                status=coverage_status(len(papers), len(full_text)),
            )
        )
    return coverage


def failed_rules(
    plan: ResearchPlan,
    coverage: Sequence[Coverage],
    contradictions: Sequence[Contradiction],
    analyses: Sequence[DocumentAnalysis],
    rules: SufficiencyRules,
) -> list[str]:
    priority1 = {sq.id for sq in plan.sub_questions if sq.priority == 1}
    evidence = [e for a in analyses for e in a.evidence]
    papers = {e.paper_id for e in evidence}
    failures = []
    if len(papers) < rules.min_papers_with_evidence:
        failures.append(
            f"only {len(papers)} paper(s) with evidence (minimum {rules.min_papers_with_evidence})"
        )
    if len(evidence) < rules.min_evidence_items:
        failures.append(
            f"only {len(evidence)} evidence item(s) (minimum {rules.min_evidence_items})"
        )
    for c in coverage:
        if (
            rules.require_priority1_covered
            and c.sub_question_id in priority1
            and c.status != "covered"
        ):
            failures.append(f"priority-1 {c.sub_question_id} is {c.status}")
        elif rules.forbid_missing_sub_questions and c.status == "missing":
            failures.append(f"{c.sub_question_id} has no evidence")
    if rules.forbid_unresolved_priority1_contradictions:
        for conflict in contradictions:
            if not conflict.resolved and conflict.sub_question_id in priority1:
                failures.append(
                    f"unresolved contradiction on priority-1 {conflict.sub_question_id}"
                )
    return failures


def validate_verdict(
    proposed: Verdict,
    plan: ResearchPlan,
    coverage: Sequence[Coverage],
    contradictions: Sequence[Contradiction],
    analyses: Sequence[DocumentAnalysis],
    rules: SufficiencyRules,
) -> ValidationOutcome:
    """Accept the proposed verdict or replace it with the one the evidence supports."""
    failures = failed_rules(plan, coverage, contradictions, analyses, rules)
    unresolved = any(not c.resolved for c in contradictions)
    unresolved_p1 = any(f.startswith("unresolved contradiction") for f in failures)
    all_covered = all(c.status == "covered" for c in coverage)

    verdict = proposed
    if proposed == "sufficient" and failures:
        verdict = "contradictory" if unresolved_p1 else "insufficient"
    elif proposed == "contradictory" and not unresolved:
        verdict = "sufficient" if not failures else "insufficient"
    elif proposed == "insufficient" and all_covered:
        # The contract requires a weak/missing sub-question for 'insufficient'.
        verdict = (
            "contradictory" if unresolved else ("sufficient" if not failures else "insufficient")
        )
    if verdict == "insufficient" and all_covered:
        verdict = "contradictory" if unresolved else "sufficient"
    return ValidationOutcome(
        verdict=verdict,
        failed_rules=tuple(failures),
        overridden=verdict != proposed,
        original_verdict=proposed,
    )
