import uuid
from typing import ClassVar, Self

from pydantic import Field, model_validator

from app.schemas.contracts.common import (
    Contract,
    LiteratureSource,
    Query,
    SearchFilters,
    ShortText,
    Strict,
    SubQuestionId,
)

MAX_PAPERS_PER_ITERATION = 6


class SearchTarget(Strict):
    sub_question_id: SubQuestionId
    queries: list[Query] = Field(min_length=1, max_length=4)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class SearchRequest(Contract):
    """Internal to the Search Agent: derived from a ResearchPlan or a ReplanningRequest."""

    schema_name: ClassVar[str] = "search_request"

    iteration: int = Field(ge=1)
    targets: list[SearchTarget] = Field(min_length=1, max_length=6)
    exclude_paper_ids: list[uuid.UUID] = Field(default_factory=list)
    k: int = Field(default=MAX_PAPERS_PER_ITERATION, ge=1, le=MAX_PAPERS_PER_ITERATION)


class QueryExecution(Strict):
    source: LiteratureSource
    query: Query
    filters: SearchFilters = Field(default_factory=SearchFilters)
    result_count: int = Field(ge=0)


class CandidatePaper(Strict):
    paper_id: uuid.UUID
    title: str = Field(min_length=1, max_length=500)
    authors: list[ShortText] = Field(default_factory=list, max_length=10)
    year: int | None = Field(default=None, ge=1800, le=2100)
    venue: ShortText | None = None
    doi: ShortText | None = None
    sub_question_ids: list[SubQuestionId] = Field(min_length=1)
    relevance_score: float = Field(ge=0, le=1)
    reason: ShortText
    has_oa_pdf: bool


class SearchResults(Contract):
    """Search → Analysis."""

    schema_name: ClassVar[str] = "search_results"

    iteration: int = Field(ge=1)
    queries_executed: list[QueryExecution] = Field(default_factory=list)
    candidates_total: int = Field(ge=0)
    duplicates_removed: int = Field(ge=0)
    degraded_sources: list[LiteratureSource] = Field(default_factory=list)
    selected: list[CandidatePaper] = Field(
        default_factory=list, max_length=MAX_PAPERS_PER_ITERATION
    )
    rejected_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        ids = [p.paper_id for p in self.selected]
        if len(ids) != len(set(ids)):
            raise ValueError("selected papers must be unique")
        if len(self.selected) + self.rejected_count > self.candidates_total:
            raise ValueError("selected + rejected cannot exceed candidates_total")
        return self
