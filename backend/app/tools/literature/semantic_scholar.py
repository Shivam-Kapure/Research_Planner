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
    clean_text,
    clean_title,
    clean_url,
    clean_year,
    normalize_doi,
)

SEMANTIC_SCHOLAR_BASE_URL = "https://api.semanticscholar.org/graph/v1"
_FIELDS = (
    "paperId,externalIds,title,abstract,year,publicationDate,authors,venue,"
    "citationCount,isOpenAccess,openAccessPdf,url"
)


class SemanticScholarClient:
    """Semantic Scholar Graph API paper search (free; secondary source).

    Works without an API key (shared public limit). An optional free key is sent in the
    `x-api-key` header, never in the URL, and is never logged.
    """

    source = "semantic_scholar"

    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        api_key: str | None = None,
        base_url: str = SEMANTIC_SCHOLAR_BASE_URL,
        timeout_s: float = 20.0,
        policy: ToolRetryPolicy | None = None,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._policy = policy or ToolRetryPolicy()
        self._limiter = limiter
        self._sleep = sleep

    async def search(self, query: SearchQuery) -> ProviderSearchResult:
        params: dict[str, str | int] = {
            "query": query.query,
            "limit": query.limit,
            "offset": (query.page - 1) * query.limit,
            "fields": _FIELDS,
        }
        if query.year_from or query.year_to:
            params["year"] = f"{query.year_from or ''}-{query.year_to or ''}"
        if query.open_access_only:
            params["openAccessPdf"] = ""
        headers = {"x-api-key": self._api_key} if self._api_key else {}

        data = await get_json(
            self._client,
            f"{self._base_url}/paper/search",
            source=self.source,
            params=params,
            headers=headers,
            timeout_s=self._timeout_s,
            policy=self._policy,
            sleep=self._sleep,
            limiter=self._limiter,
        )
        if not isinstance(data, dict):
            raise MalformedSourceResponse(self.source, "semantic scholar response is not an object")
        items = data.get("data", [])  # omitted when there are no matches
        if not isinstance(items, list):
            raise MalformedSourceResponse(self.source, "semantic scholar data is not a list")
        papers = [
            p
            for rank, item in enumerate(items[: query.limit], start=1)
            if (p := normalize_paper(item, rank)) is not None
        ]
        return ProviderSearchResult(
            source="semantic_scholar", papers=papers, total_available=clean_count(data.get("total"))
        )


def normalize_paper(item: Any, rank: int) -> Paper | None:
    if not isinstance(item, dict):
        return None
    paper_id = clean_text(item.get("paperId"), 200)
    title = clean_title(item.get("title"))
    if not paper_id or not title:
        return None
    external = as_dict(item.get("externalIds"))
    oa_pdf = as_dict(item.get("openAccessPdf"))
    raw_authors = item.get("authors")
    authors, author_count = clean_authors(
        [as_dict(a).get("name") for a in raw_authors] if isinstance(raw_authors, list) else []
    )
    pdf_url = clean_url(oa_pdf.get("url"))
    return Paper(
        title=title,
        authors=authors,
        author_count=author_count,
        year=clean_year(item.get("year")),
        publication_date=clean_date(item.get("publicationDate")),
        abstract=clean_abstract(item.get("abstract")),
        doi=normalize_doi(external.get("DOI")),
        semantic_scholar_id=paper_id,
        arxiv_id=clean_text(external.get("ArXiv"), 50),
        venue=clean_title(item.get("venue")),
        citation_count=clean_count(item.get("citationCount")),
        is_open_access=bool(item.get("isOpenAccess")) or pdf_url is not None,
        oa_pdf_url=pdf_url,
        landing_page_url=clean_url(item.get("url")),
        sources=[
            SourceRef(
                source="semantic_scholar",
                source_id=paper_id,
                rank=rank,
                url=clean_url(item.get("url")),
            )
        ],
    )
