"""Agent 2 — Literature Search: ResearchPlan (+ search revision) → SearchResults.

Reasoning loop (bounded): the LLM plans queries per sub-question → the Phase 5 tools execute
them → if too few new candidates, the LLM refines the queries once → the LLM screens the
deduplicated, pre-ranked pool in one batched call → code selects the top papers.
"""

import time
import uuid
from dataclasses import dataclass

from pydantic import Field

from app.agents.base import Agent, as_json
from app.llm.types import Message
from app.schemas.contracts import ReplanningRequest, ResearchPlan, SearchRequest, SearchResults
from app.schemas.contracts.common import ShortText, Strict, SubQuestionId
from app.schemas.contracts.search import CandidatePaper, QueryExecution, SearchTarget
from app.tools.errors import LiteratureUnavailable, ToolError
from app.tools.literature.dedupe import deduplicate
from app.tools.literature.models import Paper, SearchQuery, Source
from app.tools.literature.ranking import rank_papers

QUERY_SYSTEM = """You are the Literature Search agent of ResearchPilot. You turn a research \
plan into concrete database queries for OpenAlex and Semantic Scholar, then judge which papers \
are worth analysing. You do not analyse papers and you do not write the review.

Write short keyword queries (3-8 words, no full sentences, no boolean syntax), 1-2 per \
sub-question, priority-1 sub-questions first. Vary terminology (synonyms, outcome measures, \
study designs). Never repeat a query listed under previous_queries."""

REVISION_HINT = """This is a SEARCH REVISION requested by the Evidence Synthesis agent. Target \
exactly the gaps and contradictions in the replanning request: use its suggested queries as a \
starting point and look for papers that would close those gaps (e.g. meta-analyses, larger or \
more recent studies, the missing population)."""

REFINE_HINT = """The queries above returned too few new candidates. Propose different, broader \
or alternative-terminology queries for the same sub-questions."""

SCREEN_SYSTEM = """You are the Literature Search agent screening candidate papers. For each \
numbered candidate decide whether it should be analysed: include it only if its title/abstract \
is plausibly relevant to at least one sub-question and meets the inclusion criteria. Give a \
relevance score from 0 to 1, the sub-question ids it informs, and a short reason."""


class QueryPlan(Strict):
    targets: list[SearchTarget] = Field(min_length=1, max_length=6)
    rationale: ShortText


class ScreenDecision(Strict):
    index: int = Field(ge=0)
    include: bool
    relevance: float = Field(ge=0, le=1)
    sub_question_ids: list[SubQuestionId] = Field(default_factory=list)
    reason: ShortText


class Screening(Strict):
    decisions: list[ScreenDecision] = Field(max_length=40)


@dataclass(frozen=True)
class SearchOutcome:
    request: SearchRequest
    results: SearchResults
    papers: list[Paper]  # selected papers, full metadata for the Analysis agent


class LiteratureSearchAgent(Agent):
    node = "literature_search"
    trace_agent = "search"
    role = "search"
    _failed_calls = 0

    async def run(
        self,
        plan: ResearchPlan,
        *,
        iteration: int,
        replanning: ReplanningRequest | None,
        seen_paper_ids: set[uuid.UUID],
        previous_queries: list[str],
        papers_remaining: int,
        parent_id: uuid.UUID | None = None,
    ) -> SearchOutcome:
        limits = self.rt.limits
        self._failed_calls = 0
        query_plan = await self._plan_queries(
            plan, iteration, replanning, previous_queries, parent_id
        )
        targets = _with_directives(query_plan.targets, replanning, plan)
        request = SearchRequest(
            iteration=iteration,
            targets=targets,
            exclude_paper_ids=sorted(
                seen_paper_ids | set(replanning.exclude_paper_ids if replanning else [])
            ),
            k=max(1, min(limits.papers_per_iteration, papers_remaining)),
        )

        executions: list[QueryExecution] = []
        found: list[Paper] = []
        sq_by_key: dict[str, set[str]] = {}
        degraded: set[Source] = set()
        calls = await self._execute(
            plan,
            request.targets,
            executions,
            found,
            sq_by_key,
            degraded,
            iteration,
            parent_id,
            budget=limits.max_search_calls_per_iteration,
            seen_queries=set(previous_queries),
        )

        excluded = set(request.exclude_paper_ids)
        pool = _unique_new(found, excluded)
        refinements = 0
        while (
            len(pool) < 2 * request.k
            and refinements < limits.max_query_refinements
            and calls < limits.max_search_calls_per_iteration
        ):
            refinements += 1
            refined = await self._refine(plan, executions, iteration, parent_id)
            calls += await self._execute(
                plan,
                refined.targets,
                executions,
                found,
                sq_by_key,
                degraded,
                iteration,
                parent_id,
                budget=limits.max_search_calls_per_iteration - calls,
                seen_queries={e.query for e in executions} | set(previous_queries),
            )
            pool = _unique_new(found, excluded)

        if calls and self._failed_calls == calls:
            # Architecture §12: both sources down for every query → LITERATURE_UNAVAILABLE.
            raise LiteratureUnavailable(None, f"all {calls} literature queries failed")

        deduped = deduplicate(found)
        ranked = [r.paper for r in rank_papers(_unique_new(deduped.papers, excluded))]
        shortlist = ranked[: limits.screening_pool]
        selected, scores = await self._screen(
            plan, shortlist, request.k, sq_by_key, iteration, parent_id
        )

        candidates = [
            CandidatePaper(
                paper_id=p.paper_id,
                title=p.title,
                authors=p.authors,
                year=p.year,
                venue=p.venue,
                doi=p.doi,
                sub_question_ids=scores[p.paper_key][1],
                relevance_score=scores[p.paper_key][0],
                reason=scores[p.paper_key][2],
                has_oa_pdf=p.oa_pdf_url is not None,
            )
            for p in selected
        ]
        results = SearchResults(
            iteration=iteration,
            queries_executed=executions,
            candidates_total=len(shortlist),
            duplicates_removed=deduped.duplicates_removed,
            degraded_sources=sorted(degraded),
            selected=candidates,
            rejected_count=len(shortlist) - len(candidates),
        )
        return SearchOutcome(request=request, results=results, papers=selected)

    async def _plan_queries(
        self,
        plan: ResearchPlan,
        iteration: int,
        replanning: ReplanningRequest | None,
        previous_queries: list[str],
        parent_id: uuid.UUID | None,
    ) -> QueryPlan:
        messages = [Message("system", QUERY_SYSTEM)]
        context: dict[str, object] = {
            "iteration": iteration,
            "plan": plan.model_dump(mode="json"),
            "previous_queries": previous_queries[-20:],
        }
        if replanning:
            messages.append(Message("system", REVISION_HINT))
            context["replanning_request"] = replanning.model_dump(mode="json")
        messages.append(Message("user", as_json(context)))
        return await self.llm(
            QueryPlan, messages, iteration=iteration, parent_id=parent_id, max_output_tokens=600
        )

    async def _refine(
        self,
        plan: ResearchPlan,
        executions: list[QueryExecution],
        iteration: int,
        parent_id: uuid.UUID | None,
    ) -> QueryPlan:
        messages = [
            Message("system", QUERY_SYSTEM),
            Message("system", REFINE_HINT),
            Message(
                "user",
                as_json(
                    {
                        "plan": plan.model_dump(mode="json"),
                        "executed": [
                            {"source": e.source, "query": e.query, "results": e.result_count}
                            for e in executions
                        ],
                    }
                ),
            ),
        ]
        return await self.llm(
            QueryPlan, messages, iteration=iteration, parent_id=parent_id, max_output_tokens=600
        )

    async def _execute(
        self,
        plan: ResearchPlan,
        targets: list[SearchTarget],
        executions: list[QueryExecution],
        found: list[Paper],
        sq_by_key: dict[str, set[str]],
        degraded: set[Source],
        iteration: int,
        parent_id: uuid.UUID | None,
        *,
        budget: int,
        seen_queries: set[str],
    ) -> int:
        """Run up to `budget` distinct queries through the Phase 5 search service."""
        calls = 0
        valid_sq = plan.sub_question_ids
        for target in targets:
            if target.sub_question_id not in valid_sq:
                continue
            for text in target.queries:
                key = text.lower()
                if calls >= budget or key in seen_queries:
                    continue
                seen_queries.add(key)
                calls += 1
                years = target.filters.year_range or plan.year_range
                query = SearchQuery(
                    query=text,
                    year_from=years.start if years else None,
                    year_to=years.end if years else None,
                    limit=10,
                )
                started = time.perf_counter()
                try:
                    result = await self.rt.literature.search(query)
                except ToolError as exc:
                    self._failed_calls += 1
                    degraded.update(("openalex", "semantic_scholar"))
                    executions.append(QueryExecution(source="openalex", query=text, result_count=0))
                    await self.rt.recorder.tool_call(
                        "search",
                        iteration=iteration,
                        name="literature_search",
                        status="failed",
                        args={"query": text, "sub_question_id": target.sub_question_id},
                        result_summary=f"{exc.code}: {exc.message}",
                        duration_ms=_ms(started),
                        parent_id=parent_id,
                    )
                    continue
                for outcome in result.outcomes:
                    if outcome.status == "failed":
                        degraded.add(outcome.source)
                    if outcome.status != "skipped":
                        executions.append(
                            QueryExecution(
                                source=outcome.source, query=text, result_count=outcome.result_count
                            )
                        )
                for paper in result.papers:
                    found.append(paper)
                    sq_by_key.setdefault(paper.paper_key, set()).add(target.sub_question_id)
                await self.rt.recorder.tool_call(
                    "search",
                    iteration=iteration,
                    name="literature_search",
                    status="warning" if result.degraded_sources else "ok",
                    args={
                        "query": text,
                        "sub_question_id": target.sub_question_id,
                        "year_from": query.year_from,
                        "year_to": query.year_to,
                    },
                    result_summary=(
                        f"{len(result.papers)} papers after dedupe "
                        f"({result.duplicates_removed} duplicates removed); "
                        + ", ".join(f"{o.source}={o.status}" for o in result.outcomes)
                    ),
                    duration_ms=_ms(started),
                    parent_id=parent_id,
                )
        return calls

    async def _screen(
        self,
        plan: ResearchPlan,
        shortlist: list[Paper],
        k: int,
        sq_by_key: dict[str, set[str]],
        iteration: int,
        parent_id: uuid.UUID | None,
    ) -> tuple[list[Paper], dict[str, tuple[float, list[str], str]]]:
        if not shortlist:
            return [], {}
        candidates = [
            {
                "index": i,
                "title": p.title,
                "year": p.year,
                "venue": p.venue,
                "abstract": (p.abstract or "")[:400],
                "found_for": sorted(sq_by_key.get(p.paper_key, ())),
            }
            for i, p in enumerate(shortlist)
        ]
        screening = await self.llm(
            Screening,
            [
                Message("system", SCREEN_SYSTEM),
                Message(
                    "user",
                    as_json(
                        {
                            "sub_questions": [sq.model_dump() for sq in plan.sub_questions],
                            "inclusion_criteria": plan.inclusion_criteria,
                            "exclusion_criteria": plan.exclusion_criteria,
                            "candidates": candidates,
                        }
                    ),
                ),
            ],
            iteration=iteration,
            parent_id=parent_id,
            max_output_tokens=1500,
        )
        valid_sq = plan.sub_question_ids
        scores: dict[str, tuple[float, list[str], str]] = {}
        order: list[tuple[float, int]] = []
        for d in screening.decisions:
            if not d.include or d.index >= len(shortlist) or d.relevance < 0.5:
                continue
            paper = shortlist[d.index]
            sqs = [s for s in d.sub_question_ids if s in valid_sq] or sorted(
                s for s in sq_by_key.get(paper.paper_key, ()) if s in valid_sq
            )
            if not sqs or paper.paper_key in scores:
                continue
            scores[paper.paper_key] = (d.relevance, sqs, d.reason)
            order.append((d.relevance, d.index))
        # Highest relevance first; ties keep the deterministic pre-ranking order.
        chosen = [shortlist[i] for _, i in sorted(order, key=lambda t: (-t[0], t[1]))][:k]
        return chosen, scores


def _with_directives(
    targets: list[SearchTarget], replanning: ReplanningRequest | None, plan: ResearchPlan
) -> list[SearchTarget]:
    """A search revision must actually search for what Synthesis asked for: the directive
    queries go first, followed by the agent's own queries."""
    if not replanning or replanning.kind != "search_revision":
        return targets[:6]
    directed = [
        SearchTarget(
            sub_question_id=d.sub_question_id, queries=d.suggested_queries[:2], filters=d.filters
        )
        for d in replanning.directives
        if d.sub_question_id in plan.sub_question_ids
    ]
    return (directed + targets)[:6]


def _unique_new(papers: list[Paper], excluded: set[uuid.UUID]) -> list[Paper]:
    seen: set[str] = set()
    out = []
    for p in papers:
        if p.paper_id not in excluded and p.paper_key not in seen:
            seen.add(p.paper_key)
            out.append(p)
    return out


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
