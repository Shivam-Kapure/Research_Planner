import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx2

from app.llm.rate_limit import RateLimiter
from app.tools.errors import MalformedSourceResponse
from app.tools.http import ToolRetryPolicy, get_json
from app.tools.literature.models import Paper, ProviderSearchResult, SearchQuery, SourceRef
from app.tools.literature.normalize import (
    as_dict,
    clean_abstract,
    clean_authors,
    clean_count,
    clean_date,
    clean_title,
    clean_url,
    clean_year,
    normalize_doi,
)

OPENALEX_BASE_URL = "https://api.openalex.org"
_SELECT = (
    "id,doi,display_name,publication_year,publication_date,authorships,"
    "abstract_inverted_index,primary_location,best_oa_location,open_access,"
    "cited_by_count,relevance_score"
)
_MAX_ABSTRACT_WORDS = 1500


class OpenAlexClient:
    """OpenAlex `/works` search (free; primary source). Optional polite-pool email and
    free API key come from configuration; neither is ever logged."""

    source = "openalex"

    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        email: str | None = None,
        api_key: str | None = None,
        base_url: str = OPENALEX_BASE_URL,
        timeout_s: float = 20.0,
        policy: ToolRetryPolicy | None = None,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._email = email
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._policy = policy or ToolRetryPolicy()
        self._limiter = limiter
        self._sleep = sleep

    async def search(self, query: SearchQuery) -> ProviderSearchResult:
        params: dict[str, str | int] = {
            "search": query.query,
            "per_page": query.limit,
            "page": query.page,
            "select": _SELECT,
        }
        filters = []
        if query.year_from or query.year_to:
            filters.append(f"publication_year:{query.year_from or ''}-{query.year_to or ''}")
        if query.open_access_only:
            filters.append("is_oa:true")
        if filters:
            params["filter"] = ",".join(filters)
        if self._email:
            params["mailto"] = self._email
        if self._api_key:
            params["api_key"] = self._api_key

        data = await get_json(
            self._client,
            f"{self._base_url}/works",
            source=self.source,
            params=params,
            timeout_s=self._timeout_s,
            policy=self._policy,
            sleep=self._sleep,
            limiter=self._limiter,
        )
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise MalformedSourceResponse(self.source, "openalex response has no results list")
        papers = [
            p
            for rank, work in enumerate(data["results"][: query.limit], start=1)
            if (p := normalize_work(work, rank)) is not None
        ]
        return ProviderSearchResult(
            source="openalex",
            papers=papers,
            total_available=clean_count(as_dict(data.get("meta")).get("count")),
        )


def normalize_work(work: Any, rank: int) -> Paper | None:
    """One OpenAlex work → Paper. Unusable records (no id or title) are skipped."""
    if not isinstance(work, dict):
        return None
    openalex_id = _short_id(work.get("id"))
    title = clean_title(work.get("display_name") or work.get("title"))
    if not openalex_id or not title:
        return None
    authors, author_count = clean_authors(
        [as_dict(as_dict(a).get("author")).get("display_name") for a in _list(work, "authorships")]
    )
    primary = as_dict(work.get("primary_location"))
    best_oa = as_dict(work.get("best_oa_location"))
    open_access = as_dict(work.get("open_access"))
    source = as_dict(primary.get("source"))
    score = work.get("relevance_score")
    return Paper(
        title=title,
        authors=authors,
        author_count=author_count,
        year=clean_year(work.get("publication_year")),
        publication_date=clean_date(work.get("publication_date")),
        abstract=clean_abstract(_rebuild_abstract(work.get("abstract_inverted_index"))),
        doi=normalize_doi(work.get("doi")),
        openalex_id=openalex_id,
        venue=clean_title(source.get("display_name")),
        citation_count=clean_count(work.get("cited_by_count")),
        is_open_access=bool(open_access.get("is_oa")),
        # Only an explicit open-access PDF location counts as full text.
        oa_pdf_url=clean_url(best_oa.get("pdf_url")),
        landing_page_url=clean_url(primary.get("landing_page_url")),
        sources=[
            SourceRef(
                source="openalex",
                source_id=openalex_id,
                rank=rank,
                relevance_score=float(score) if isinstance(score, int | float) else None,
                url=f"https://openalex.org/{openalex_id}",
            )
        ],
    )


def _list(obj: dict[str, Any], key: str) -> list[Any]:
    value = obj.get(key)
    return value if isinstance(value, list) else []


def _short_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    short = value.rsplit("/", 1)[-1]
    return short if short[:1] == "W" and short[1:].isdigit() else None


def _rebuild_abstract(index: object) -> str | None:
    """OpenAlex ships abstracts as {word: [positions]}; rebuild with a hard size bound."""
    if not isinstance(index, dict):
        return None
    words: dict[int, str] = {}
    for word, positions in index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for pos in positions:
            if isinstance(pos, int) and 0 <= pos < _MAX_ABSTRACT_WORDS:
                words[pos] = word
    return " ".join(words[i] for i in sorted(words)) or None
