"""Deterministic multi-source literature search (no LLM, no research strategy).

The future Search Agent decides what to query and when; this service only executes one query
against the configured sources, normalises, deduplicates and bounds the results.
"""

import asyncio
from collections.abc import Sequence
from typing import Protocol

import httpx2

from app.config import Settings
from app.llm.rate_limit import RateLimiter
from app.tools.errors import LiteratureUnavailable, ToolError
from app.tools.literature.dedupe import deduplicate
from app.tools.literature.models import (
    MAX_COMBINED_RESULTS,
    SOURCES,
    LiteratureSearchResult,
    Paper,
    ProviderSearchResult,
    SearchQuery,
    Source,
    SourceOutcome,
)
from app.tools.literature.openalex import OpenAlexClient
from app.tools.literature.semantic_scholar import SemanticScholarClient


class LiteratureSource(Protocol):
    source: str

    async def search(self, query: SearchQuery) -> ProviderSearchResult: ...


class LiteratureSearchService:
    def __init__(self, clients: dict[Source, LiteratureSource]) -> None:
        self._clients = clients

    async def search(
        self,
        query: SearchQuery,
        *,
        sources: Sequence[Source] = SOURCES,
        max_results: int = MAX_COMBINED_RESULTS,
    ) -> LiteratureSearchResult:
        """One request per source (in parallel); results are combined primary-source first.

        A failed source degrades the result instead of failing it; only when every requested
        source fails is LiteratureUnavailable raised.
        """
        requested = [s for s in SOURCES if s in sources]  # canonical order: OpenAlex first
        active = [s for s in requested if s in self._clients]
        results = await asyncio.gather(
            *(self._clients[s].search(query) for s in active), return_exceptions=True
        )

        outcomes: list[SourceOutcome] = []
        candidates: list[Paper] = []
        by_source = dict(zip(active, results, strict=True))
        for source in requested:
            result = by_source.get(source)
            if source not in by_source:
                outcomes.append(SourceOutcome(source=source, status="skipped"))
            elif isinstance(result, ProviderSearchResult):
                candidates.extend(result.papers)
                outcomes.append(
                    SourceOutcome(
                        source=source,
                        status="ok",
                        result_count=len(result.papers),
                        total_available=result.total_available,
                    )
                )
            elif isinstance(result, ToolError):
                outcomes.append(
                    SourceOutcome(source=source, status="failed", error_code=result.code)
                )
            else:
                raise result  # type: ignore[misc]  # a programming error, not a source failure

        if not any(o.status == "ok" for o in outcomes):
            codes = ", ".join(f"{o.source}={o.error_code or o.status}" for o in outcomes)
            raise LiteratureUnavailable(None, f"no literature source succeeded ({codes})")

        deduped = deduplicate(candidates)
        return LiteratureSearchResult(
            query=query,
            papers=deduped.papers[: min(max_results, MAX_COMBINED_RESULTS)],
            outcomes=outcomes,
            candidates_total=len(candidates),
            duplicates_removed=deduped.duplicates_removed,
        )


def build_literature_service(
    settings: Settings, http_client: httpx2.AsyncClient
) -> LiteratureSearchService:
    """Wire both free sources from configuration. Keys are optional and never logged."""
    s2_key = settings.semantic_scholar_api_key
    oa_key = settings.openalex_api_key
    return LiteratureSearchService(
        {
            "openalex": OpenAlexClient(
                http_client,
                email=settings.openalex_email,
                api_key=oa_key.get_secret_value() if oa_key else None,
                timeout_s=settings.literature_timeout_s,
            ),
            "semantic_scholar": SemanticScholarClient(
                http_client,
                api_key=s2_key.get_secret_value() if s2_key else None,
                timeout_s=settings.literature_timeout_s,
                limiter=RateLimiter(settings.semantic_scholar_requests_per_minute),
            ),
        }
    )
