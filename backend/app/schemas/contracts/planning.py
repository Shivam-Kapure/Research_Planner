import re
from typing import ClassVar, Self

from pydantic import Field, model_validator

from app.schemas.contracts.common import (
    Contract,
    ShortText,
    Strict,
    SubQuestionId,
    Text,
    YearRange,
)


class ResearchRequest(Contract):
    """User → Planner."""

    schema_name: ClassVar[str] = "research_request"

    question: str = Field(min_length=15, max_length=1000)
    max_iterations: int = Field(default=3, ge=1, le=3)
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)

    @model_validator(mode="after")
    def _years_ordered(self) -> Self:
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from must not be after year_to")
        return self


class SubQuestion(Strict):
    id: SubQuestionId
    text: str = Field(min_length=10, max_length=500)
    rationale: ShortText
    priority: int = Field(ge=1, le=3)  # 1 = must be answered for the evidence to be sufficient


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z0-9]{3,}", text.lower())}


class ResearchPlan(Contract):
    """Planner → Search. Versioned: a scope revision produces plan_version + 1."""

    schema_name: ClassVar[str] = "research_plan"

    plan_version: int = Field(ge=1)
    objective: Text
    sub_questions: list[SubQuestion] = Field(min_length=2, max_length=6)
    search_strategy: Text
    inclusion_criteria: list[ShortText] = Field(min_length=1, max_length=10)
    exclusion_criteria: list[ShortText] = Field(default_factory=list, max_length=10)
    keywords: list[ShortText] = Field(min_length=3, max_length=20)
    year_range: YearRange | None = None
    study_types: list[ShortText] = Field(default_factory=list, max_length=6)
    revision_reason: Text | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        ids = [sq.id for sq in self.sub_questions]
        if len(ids) != len(set(ids)):
            raise ValueError("sub-question ids must be unique")
        if not any(sq.priority == 1 for sq in self.sub_questions):
            raise ValueError("at least one sub-question must have priority 1")
        if self.plan_version > 1 and not self.revision_reason:
            raise ValueError("revision_reason is required when plan_version > 1")
        keyword_stems = set().union(*(_stems(k) for k in self.keywords))
        for sq in self.sub_questions:
            if not _stems(sq.text) & keyword_stems:
                raise ValueError(f"sub-question {sq.id} shares no term with the keywords")
        return self

    @property
    def sub_question_ids(self) -> set[str]:
        return {sq.id for sq in self.sub_questions}
