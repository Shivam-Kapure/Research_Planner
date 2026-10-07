"""Runtime dependencies and bounds for one research run.

Everything here lives outside the LangGraph state: the LLM gateway (which can decrypt the
user's provider keys on demand), HTTP-backed tools and the trace recorder. Graph state only
ever holds research data.
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.llm.errors import LLMError
from app.llm.gateway import AttemptRecord, LLMGateway
from app.orchestration.validation import SufficiencyRules
from app.services.trace_recorder import TraceRecorder
from app.tools.documents.pdf import SafePdfFetcher
from app.tools.literature.models import LiteratureSearchResult, SearchQuery, Source


@dataclass(frozen=True)
class ResearchLimits:
    """Architecture §6.1 / §12 bounds."""

    max_iterations: int = 3
    papers_per_iteration: int = 6
    max_papers_per_run: int = 15
    max_search_calls_per_iteration: int = 6
    max_query_refinements: int = 1  # query plan + ≤1 refinement + screening ≤ 3 LLM steps
    screening_pool: int = 40
    analysis_concurrency: int = 2
    excerpt_chars: int = 16_000
    max_llm_calls: int = 60
    max_tokens: int = 200_000
    writer_reserve_calls: int = 4  # kept back so the Writer can always run
    recursion_limit: int = 40  # LangGraph super-step guard (longest legal path = 15 steps)
    run_timeout_s: float = 20 * 60


class BudgetExhausted(LLMError):
    code = "budget_exhausted"


@dataclass
class RunBudget:
    """Counts LLM calls and tokens for the run (metadata from AttemptRecords)."""

    limits: ResearchLimits
    calls: int = 0
    tokens: int = 0

    def record(self, attempts: tuple[AttemptRecord, ...]) -> None:
        self.calls += len(attempts)
        self.tokens += sum((a.input_tokens or 0) + (a.output_tokens or 0) for a in attempts)

    def check(self, *, writer: bool = False) -> None:
        reserve = 0 if writer else self.limits.writer_reserve_calls
        if (
            self.calls >= self.limits.max_llm_calls - reserve
            or self.tokens >= self.limits.max_tokens
        ):
            raise BudgetExhausted(
                None, f"LLM budget used: {self.calls} calls, {self.tokens} tokens"
            )

    def can_afford_iteration(self) -> bool:
        """Rough upper estimate of one more iteration (search 3 + 2 per paper + synthesis)."""
        estimate = 3 + 2 * self.limits.papers_per_iteration + 1
        remaining = self.limits.max_llm_calls - self.limits.writer_reserve_calls - self.calls
        return remaining >= estimate and self.tokens < self.limits.max_tokens * 0.85


class LiteratureSearch(Protocol):
    async def search(
        self, query: SearchQuery, *, sources: tuple[Source, ...] = ..., max_results: int = ...
    ) -> LiteratureSearchResult: ...


@dataclass
class ResearchRuntime:
    gateway: LLMGateway
    literature: LiteratureSearch
    fetcher: SafePdfFetcher
    recorder: TraceRecorder
    limits: ResearchLimits = field(default_factory=ResearchLimits)
    rules: SufficiencyRules = field(default_factory=SufficiencyRules)
    budget: RunBudget = field(init=False)

    def __post_init__(self) -> None:
        self.budget = RunBudget(self.limits)
