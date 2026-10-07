import uuid
from typing import ClassVar, Literal, Self

from pydantic import Field, model_validator

from app.schemas.contracts.common import (
    Contract,
    Query,
    SearchFilters,
    ShortText,
    Strict,
    SubQuestionId,
    Text,
)

Verdict = Literal["sufficient", "insufficient", "contradictory"]
CoverageStatus = Literal["covered", "weak", "missing"]


def coverage_status(supporting_papers: int, full_text_papers: int) -> CoverageStatus:
    """Architecture §12: covered = ≥2 papers incl. ≥1 full text; weak = 1 paper or abstract
    evidence only; missing = none."""
    if supporting_papers == 0:
        return "missing"
    if supporting_papers >= 2 and full_text_papers >= 1:
        return "covered"
    return "weak"


class Coverage(Strict):
    sub_question_id: SubQuestionId
    supporting_papers: int = Field(ge=0)
    full_text_papers: int = Field(ge=0)
    status: CoverageStatus

    @model_validator(mode="after")
    def _status_matches_counts(self) -> Self:
        if self.full_text_papers > self.supporting_papers:
            raise ValueError("full_text_papers cannot exceed supporting_papers")
        expected = coverage_status(self.supporting_papers, self.full_text_papers)
        if self.status != expected:
            raise ValueError(f"coverage status must be {expected!r} for these counts")
        return self


class Contradiction(Strict):
    sub_question_id: SubQuestionId
    claim_a: uuid.UUID  # evidence item ids
    claim_b: uuid.UUID
    explanation: Text
    resolved: bool = False
    moderator: ShortText | None = None  # e.g. population, method, time period

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.claim_a == self.claim_b:
            raise ValueError("a contradiction needs two different evidence items")
        if self.resolved and not self.moderator:
            raise ValueError("a resolved contradiction must name its moderator")
        return self


class Theme(Strict):
    title: ShortText
    summary: Text
    evidence_ids: list[uuid.UUID] = Field(min_length=1)


class ValidatorOverride(Strict):
    original_verdict: Verdict
    rule_failed: ShortText


class SynthesisDecision(Contract):
    """Synthesis → router (and Writer). The verdict drives the replanning loop."""

    schema_name: ClassVar[str] = "synthesis_decision"

    iteration: int = Field(ge=1)
    verdict: Verdict
    coverage: list[Coverage] = Field(min_length=1)
    contradictions: list[Contradiction] = Field(default_factory=list)
    themes: list[Theme] = Field(default_factory=list)
    rationale: Text
    validator_override: ValidatorOverride | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        ids = [c.sub_question_id for c in self.coverage]
        if len(ids) != len(set(ids)):
            raise ValueError("coverage must list each sub-question once")
        unresolved = [c for c in self.contradictions if not c.resolved]
        if self.verdict == "sufficient" and any(c.status == "missing" for c in self.coverage):
            raise ValueError("'sufficient' is impossible while a sub-question is missing")
        if self.verdict == "contradictory" and not unresolved:
            raise ValueError("'contradictory' requires at least one unresolved contradiction")
        if self.verdict == "insufficient" and all(c.status == "covered" for c in self.coverage):
            raise ValueError("'insufficient' requires a weak or missing sub-question")
        return self

    def unresolved_contradiction_ids(self) -> set[str]:
        return {c.sub_question_id for c in self.contradictions if not c.resolved}


class ReplanReason(Strict):
    type: Literal["gap", "contradiction", "low_quality"]
    sub_question_id: SubQuestionId
    detail: ShortText


class SearchDirective(Strict):
    sub_question_id: SubQuestionId
    suggested_queries: list[Query] = Field(min_length=1, max_length=4)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class ReplanningRequest(Contract):
    """Synthesis → Search (search_revision) or Planner (scope_revision): why another research
    cycle is needed and what should change."""

    schema_name: ClassVar[str] = "replanning_request"

    iteration_from: int = Field(ge=1)
    kind: Literal["search_revision", "scope_revision"]
    reasons: list[ReplanReason] = Field(min_length=1)
    directives: list[SearchDirective] = Field(default_factory=list, max_length=6)
    scope_change: Text | None = None
    exclude_paper_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.kind == "search_revision" and not self.directives:
            raise ValueError("a search_revision needs at least one search directive")
        if self.kind == "scope_revision" and not self.scope_change:
            raise ValueError("a scope_revision must describe the scope_change")
        return self

    def check_against(self, decision: SynthesisDecision) -> None:
        """Each reason must be backed by the decision it came from (architecture §9)."""
        if decision.iteration != self.iteration_from:
            raise ValueError("replanning request does not match the decision's iteration")
        if decision.verdict == "sufficient":
            raise ValueError("cannot replan after a 'sufficient' verdict")
        not_covered = {c.sub_question_id for c in decision.coverage if c.status != "covered"}
        contradicted = decision.unresolved_contradiction_ids()
        for reason in self.reasons:
            backing = contradicted if reason.type == "contradiction" else not_covered
            if reason.sub_question_id not in backing:
                raise ValueError(
                    f"reason {reason.type!r} for {reason.sub_question_id} is not supported "
                    "by the synthesis decision"
                )
