"""Agent 4 — Evidence Synthesis: all evidence so far → SynthesisDecision (+ ReplanningRequest).

The coverage table is computed by code from the evidence. The LLM compares the evidence across
papers and proposes a verdict, contradictions, themes and — when more research is needed — a
replanning request. The deterministic validator then accepts or overrides the verdict, and the
replanning request is checked against the validated decision before it is handed on.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from app.agents.base import Agent, as_json
from app.llm.types import Message
from app.orchestration.validation import compute_coverage, validate_verdict
from app.schemas.contracts import (
    DocumentAnalysis,
    ReplanningRequest,
    ResearchPlan,
    SynthesisDecision,
)
from app.schemas.contracts.common import Strict, Text
from app.schemas.contracts.synthesis import (
    Contradiction,
    Coverage,
    ReplanReason,
    SearchDirective,
    Theme,
    ValidatorOverride,
    Verdict,
)
from app.tools.literature.models import Paper

SYSTEM = """You are the Evidence Synthesis agent of ResearchPilot. You compare evidence \
extracted from several papers and decide whether it is enough to write a literature review. \
You do not search and you do not write the review.

Using the evidence items and the coverage table (computed by the system, trust it):
- Identify themes (agreements) and contradictions (two evidence items whose claims conflict). \
Mark a contradiction resolved only if you can name a moderator (population, method, time \
period, dose...) that explains it.
- verdict: "sufficient" if every priority-1 sub-question is well covered and no essential \
conflict is unresolved; "contradictory" if unresolved conflicts block a conclusion; otherwise \
"insufficient". Explain in rationale exactly what is missing or conflicting.
- If the verdict is not sufficient, propose replanning:
  * kind "search_revision": the plan is fine but more/different literature is needed. Give \
directives with 1-4 targeted keyword queries for each weak, missing or contradicted \
sub-question (e.g. meta-analyses, larger or more recent studies, the missing population).
  * kind "scope_revision": the question itself must change (too broad, unanswerable as \
posed, needs to be split by a moderator). Describe the change in scope_change.
Refer to evidence only by the ids given."""


class ReplanDraft(Strict):
    kind: Literal["search_revision", "scope_revision"]
    directives: list[SearchDirective] = Field(default_factory=list, max_length=6)
    scope_change: Text | None = None


class SynthesisDraft(Strict):
    verdict: Verdict
    rationale: Text
    themes: list[Theme] = Field(default_factory=list, max_length=8)
    contradictions: list[Contradiction] = Field(default_factory=list, max_length=8)
    replanning: ReplanDraft | None = None


@dataclass(frozen=True)
class SynthesisOutcome:
    decision: SynthesisDecision
    replanning: ReplanningRequest | None  # set when the validated verdict is not sufficient


class EvidenceSynthesisAgent(Agent):
    node = "evidence_synthesis"
    trace_agent = "synthesis"
    role = "synthesis"

    async def run(
        self,
        plan: ResearchPlan,
        analyses: list[DocumentAnalysis],
        papers: dict[str, Paper],
        *,
        iteration: int,
        previous: list[SynthesisDecision],
        parent_id: uuid.UUID | None = None,
    ) -> SynthesisOutcome:
        coverage = compute_coverage(plan, analyses)
        evidence_ids = {e.id for a in analyses for e in a.evidence}
        draft = await self.llm(
            SynthesisDraft,
            [
                Message("system", SYSTEM),
                Message(
                    "user", as_json(_context(plan, analyses, papers, coverage, iteration, previous))
                ),
            ],
            iteration=iteration,
            parent_id=parent_id,
            max_output_tokens=2000,
        )

        # References to evidence that does not exist are dropped, not trusted.
        contradictions = [
            c
            for c in draft.contradictions
            if c.claim_a in evidence_ids
            and c.claim_b in evidence_ids
            and c.sub_question_id in plan.sub_question_ids
        ]
        themes = [
            t.model_copy(update={"evidence_ids": [i for i in t.evidence_ids if i in evidence_ids]})
            for t in draft.themes
            if any(i in evidence_ids for i in t.evidence_ids)
        ]
        dropped = (len(draft.contradictions) - len(contradictions)) + (
            len(draft.themes) - len(themes)
        )

        outcome = validate_verdict(
            draft.verdict, plan, coverage, contradictions, analyses, self.rt.rules
        )
        override = (
            ValidatorOverride(
                original_verdict=outcome.original_verdict,
                rule_failed="; ".join(outcome.failed_rules)[:300]
                or "verdict inconsistent with coverage",
            )
            if outcome.overridden
            else None
        )
        decision = SynthesisDecision(
            iteration=iteration,
            verdict=outcome.verdict,
            coverage=coverage,
            contradictions=contradictions,
            themes=themes,
            rationale=draft.rationale,
            validator_override=override,
        )
        await self.rt.recorder.validation(
            "synthesis",
            iteration=iteration,
            schema_name="synthesis_decision",
            passed=not outcome.failed_rules,
            errors=list(outcome.failed_rules),
            dropped_items=dropped,
            override=(
                f"LLM verdict '{outcome.original_verdict}' overridden to '{outcome.verdict}'"
                if outcome.overridden
                else None
            ),
            parent_id=parent_id,
        )
        await self.rt.recorder.decision(
            "synthesis",
            iteration=iteration,
            route=decision.verdict,
            rationale=decision.rationale,
            parent_id=parent_id,
        )
        replanning = (
            None if decision.verdict == "sufficient" else _replanning(decision, draft, plan)
        )
        return SynthesisOutcome(decision=decision, replanning=replanning)


def _context(
    plan: ResearchPlan,
    analyses: list[DocumentAnalysis],
    papers: dict[str, Paper],
    coverage: list[Coverage],
    iteration: int,
    previous: list[SynthesisDecision],
) -> dict[str, object]:
    evidence = [
        {
            "id": str(e.id),
            "paper": papers[str(a.paper_id)].title[:120]
            if str(a.paper_id) in papers
            else str(a.paper_id),
            "basis": a.basis,
            "sub_question_id": e.sub_question_id,
            "stance": e.stance,
            "claim": e.claim,
            "confidence": e.confidence,
        }
        for a in analyses
        for e in a.evidence
    ][:80]
    return {
        "iteration": iteration,
        "objective": plan.objective,
        "sub_questions": [sq.model_dump() for sq in plan.sub_questions],
        "coverage": [c.model_dump() for c in coverage],
        "evidence": evidence,
        "papers_without_evidence": sum(1 for a in analyses if not a.evidence),
        "previous_verdicts": [
            {"iteration": d.iteration, "verdict": d.verdict, "rationale": d.rationale}
            for d in previous
        ],
    }


def _replanning(
    decision: SynthesisDecision, draft: SynthesisDraft, plan: ResearchPlan
) -> ReplanningRequest:
    """Turn the validated decision (+ the LLM's suggestions) into a ReplanningRequest whose every
    reason is backed by the decision (ReplanningRequest.check_against)."""
    contradicted = decision.unresolved_contradiction_ids()
    reasons = [
        ReplanReason(type="contradiction", sub_question_id=sq, detail="unresolved contradiction")
        for sq in sorted(contradicted)
    ] + [
        ReplanReason(
            type="gap" if c.status == "missing" else "low_quality",
            sub_question_id=c.sub_question_id,
            detail=f"{c.status}: {c.supporting_papers} paper(s), {c.full_text_papers} full text",
        )
        for c in decision.coverage
        if c.status != "covered"
    ]
    if not reasons:  # e.g. validator kept 'insufficient' on rules alone: point at priority-1
        weakest = min(decision.coverage, key=lambda c: (c.supporting_papers, c.sub_question_id))
        reasons = [
            ReplanReason(
                type="low_quality",
                sub_question_id=weakest.sub_question_id,
                detail="too little evidence overall",
            )
        ]

    proposal = draft.replanning
    kind = proposal.kind if proposal else "search_revision"
    needed = {r.sub_question_id for r in reasons}
    directives = [
        d
        for d in (proposal.directives if proposal else [])
        if d.sub_question_id in plan.sub_question_ids
    ]
    covered_by_directive = {d.sub_question_id for d in directives}
    for sq in plan.sub_questions:  # every reason gets at least one concrete search directive
        if sq.id in needed and sq.id not in covered_by_directive:
            directives.append(
                SearchDirective(
                    sub_question_id=sq.id,
                    suggested_queries=[_fallback_query(sq.text, plan.keywords)],
                )
            )
    scope_change = proposal.scope_change if proposal and proposal.scope_change else None
    if kind == "scope_revision" and not scope_change:
        kind = "search_revision"
    request = ReplanningRequest(
        iteration_from=decision.iteration,
        kind=kind,
        reasons=reasons,
        directives=directives[:6],
        scope_change=scope_change,
    )
    request.check_against(decision)
    return request


def _fallback_query(text: str, keywords: list[str]) -> str:
    words = [w for w in text.replace("?", "").split() if len(w) > 3][:5]
    query = " ".join(words) or keywords[0]
    return (query + " review")[:300]
