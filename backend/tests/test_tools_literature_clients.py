import logging
from typing import Any

import httpx2
import pytest
from pydantic import ValidationError

from app.tools.errors import (
    InvalidToolRequest,
    MalformedSourceResponse,
    SourceRateLimited,
    SourceTimeout,
    SourceUnavailable,
)
from app.tools.literature.models import MAX_RESULTS_PER_SOURCE, SearchQuery
from app.tools.literature.openalex import OpenAlexClient
from app.tools.literature.semantic_scholar import SemanticScholarClient
from tests.llm_fakes import FakeClock, Recorder, json_response

pytestmark = pytest.mark.anyio

OPENALEX_KEY = "oa-TESTONLY-key-0000"
S2_KEY = "s2-TESTONLY-key-0000"


def work(n: int, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": f"https://openalex.org/W{n}",
        "doi": f"https://doi.org/10.1000/ABC.{n}",
        "display_name": f"Sleep and memory study {n}",
        "publication_year": 2020,
        "publication_date": "2020-05-01",
        "authorships": [
            {"author": {"display_name": "Ana Smith"}},
            {"author": {"display_name": "B. Lee"}},
        ],
        "abstract_inverted_index": {"Sleep": [0], "supports": [1], "memory.": [2]},
        "primary_location": {
            "landing_page_url": f"https://journal.example/article/{n}",
            "source": {"display_name": "Journal of Sleep"},
        },
        "best_oa_location": {"pdf_url": f"https://repo.example/{n}.pdf"},
        "open_access": {"is_oa": True},
        "cited_by_count": 12,
        "relevance_score": 3.5,
    }
    data.update(overrides)
    return data


def openalex(recorder: Recorder, clock: FakeClock | None = None, **kwargs: Any) -> OpenAlexClient:
    return OpenAlexClient(recorder.client(), sleep=(clock or FakeClock()).sleep, **kwargs)


def s2(recorder: Recorder, clock: FakeClock | None = None, **kwargs: Any) -> SemanticScholarClient:
    return SemanticScholarClient(recorder.client(), sleep=(clock or FakeClock()).sleep, **kwargs)


# ---------------- OpenAlex ----------------


async def test_openalex_search_and_normalisation() -> None:
    recorder = Recorder(
        json_response(200, {"meta": {"count": 1234}, "results": [work(1), {"id": "x"}, work(2)]})
    )
    query = SearchQuery(
        query="sleep memory", year_from=2015, year_to=2024, open_access_only=True, limit=5
    )
    result = await openalex(recorder, email="team@example.org").search(query)

    params = recorder.requests[0].url.params
    assert recorder.requests[0].url.path == "/works"
    assert (
        params["search"] == "sleep memory" and params["per_page"] == "5" and params["page"] == "1"
    )
    assert params["filter"] == "publication_year:2015-2024,is_oa:true"
    assert params["mailto"] == "team@example.org" and "api_key" not in params

    assert result.source == "openalex" and result.total_available == 1234
    assert len(result.papers) == 2  # the record without a title/id is skipped
    p = result.papers[0]
    assert p.doi == "10.1000/abc.1" and p.paper_key == "doi:10.1000/abc.1"
    assert p.openalex_id == "W1" and p.title == "Sleep and memory study 1"
    assert p.authors == ["Ana Smith", "B. Lee"] and p.author_count == 2
    assert p.abstract == "Sleep supports memory."
    assert p.venue == "Journal of Sleep" and p.citation_count == 12 and p.year == 2020
    assert p.is_open_access and p.oa_pdf_url == "https://repo.example/1.pdf"
    assert p.sources[0].source == "openalex" and p.sources[0].rank == 1
    assert p.sources[0].relevance_score == 3.5


async def test_openalex_result_count_is_bounded() -> None:
    recorder = Recorder(json_response(200, {"results": [work(i) for i in range(1, 30)]}))
    result = await openalex(recorder).search(SearchQuery(query="sleep", limit=3))
    assert len(result.papers) == 3
    with pytest.raises(ValidationError):
        SearchQuery(query="sleep", limit=MAX_RESULTS_PER_SOURCE + 1)
    with pytest.raises(ValidationError):
        SearchQuery(query="sleep", page=4)  # no unbounded pagination


async def test_openalex_empty_result() -> None:
    result = await openalex(
        Recorder(json_response(200, {"meta": {"count": 0}, "results": []}))
    ).search(SearchQuery(query="nothing matches this"))
    assert result.papers == [] and result.total_available == 0


async def test_openalex_tolerates_malformed_fields() -> None:
    odd = work(
        3,
        doi="not-a-doi",
        authorships="nonsense",
        abstract_inverted_index={"word": [0, -1, 99_999]},
        best_oa_location="x",
        publication_year="2020",
        cited_by_count=-5,
    )
    paper = (
        await openalex(Recorder(json_response(200, {"results": [odd]}))).search(
            SearchQuery(query="sleep")
        )
    ).papers[0]
    assert paper.doi is None and paper.authors == [] and paper.abstract == "word"
    assert paper.oa_pdf_url is None and paper.year is None and paper.citation_count is None


@pytest.mark.parametrize(
    "response",
    [
        json_response(200, {"meta": {}}),  # no results list
        json_response(200, ["not", "an", "object"]),
        httpx2.Response(200, text="<html>maintenance</html>"),
        httpx2.Response(200, content=b"{" + b" " * (3 * 1024 * 1024) + b"}"),  # over 2 MB
    ],
    ids=["no-results", "not-object", "not-json", "too-large"],
)
async def test_openalex_malformed_responses(response: httpx2.Response) -> None:
    with pytest.raises(MalformedSourceResponse):
        await openalex(Recorder(response)).search(SearchQuery(query="sleep"))


async def test_openalex_timeout_is_retried_then_reported() -> None:
    recorder = Recorder(*[httpx2.ReadTimeout("slow")] * 3)
    clock = FakeClock()
    with pytest.raises(SourceTimeout):
        await openalex(recorder, clock).search(SearchQuery(query="sleep"))
    assert len(recorder.requests) == 3 and clock.sleeps == [1.0, 2.0]


async def test_openalex_429_honours_retry_after() -> None:
    clock = FakeClock()
    recorder = Recorder(
        json_response(429, {}, headers={"retry-after": "4"}),
        json_response(200, {"results": [work(1)]}),
    )
    result = await openalex(recorder, clock).search(SearchQuery(query="sleep"))
    assert len(result.papers) == 1 and clock.sleeps == [4.0]


async def test_openalex_429_with_long_retry_after_fails_fast() -> None:
    recorder = Recorder(json_response(429, {}, headers={"retry-after": "3600"}))
    with pytest.raises(SourceRateLimited):
        await openalex(recorder).search(SearchQuery(query="sleep"))
    assert len(recorder.requests) == 1


async def test_openalex_5xx_is_retried_and_bounded() -> None:
    recorder = Recorder(*[json_response(503, {})] * 3)
    with pytest.raises(SourceUnavailable):
        await openalex(recorder).search(SearchQuery(query="sleep"))
    assert len(recorder.requests) == 3


async def test_openalex_4xx_is_not_retried() -> None:
    recorder = Recorder(json_response(400, {"error": "bad filter"}))
    with pytest.raises(InvalidToolRequest):
        await openalex(recorder).search(SearchQuery(query="sleep"))
    assert len(recorder.requests) == 1


async def test_openalex_api_key_never_logged_or_in_errors(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    recorder = Recorder(
        json_response(200, {"results": []}),
        json_response(500, {}),
        json_response(500, {}),
        json_response(500, {}),
    )
    client = openalex(recorder, api_key=OPENALEX_KEY)
    await client.search(SearchQuery(query="sleep"))
    assert recorder.requests[0].url.params["api_key"] == OPENALEX_KEY  # sent to OpenAlex
    with pytest.raises(SourceUnavailable) as exc_info:
        await client.search(SearchQuery(query="sleep"))
    assert any("HTTP Request" in r.getMessage() for r in caplog.records)  # URLs were logged
    assert OPENALEX_KEY not in caplog.text  # …but without their query strings
    assert OPENALEX_KEY not in f"{exc_info.value} {exc_info.value!r}"
    assert exc_info.value.__context__ is None


# ---------------- Semantic Scholar ----------------

S2_ITEM = {
    "paperId": "649def34f8be52c8b66281af98ae884c09aef38b",
    "externalIds": {"DOI": "10.1000/ABC.1", "ArXiv": "2001.01234"},
    "title": "Sleep and memory study 1",
    "abstract": "A longer Semantic Scholar abstract about sleep and memory.",
    "year": 2020,
    "publicationDate": "2020-05-01",
    "authors": [{"name": "Ana Smith"}],
    "venue": "Journal of Sleep",
    "citationCount": 15,
    "isOpenAccess": True,
    "openAccessPdf": {"url": "https://arxiv.org/pdf/2001.01234", "status": "GREEN"},
    "url": "https://www.semanticscholar.org/paper/649def34",
}


async def test_s2_search_without_api_key() -> None:
    recorder = Recorder(
        json_response(200, {"total": 2, "offset": 0, "data": [S2_ITEM, {"title": None}]})
    )
    result = await s2(recorder).search(
        SearchQuery(query="sleep memory", year_from=2018, limit=5, page=2)
    )

    request = recorder.requests[0]
    assert request.url.path == "/graph/v1/paper/search"
    assert request.url.params["offset"] == "5" and request.url.params["year"] == "2018-"
    assert "x-api-key" not in request.headers
    assert result.total_available == 2 and len(result.papers) == 1
    p = result.papers[0]
    assert p.semantic_scholar_id == S2_ITEM["paperId"] and p.doi == "10.1000/abc.1"
    assert p.arxiv_id == "2001.01234" and p.oa_pdf_url == "https://arxiv.org/pdf/2001.01234"
    assert p.is_open_access and p.citation_count == 15 and p.authors == ["Ana Smith"]


async def test_s2_api_key_goes_in_header_only(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    recorder = Recorder(json_response(200, {"data": []}), json_response(403, {}))
    client = s2(recorder, api_key=S2_KEY)
    await client.search(SearchQuery(query="sleep", open_access_only=True))
    request = recorder.requests[0]
    assert request.headers["x-api-key"] == S2_KEY
    assert S2_KEY not in str(request.url)
    assert "openAccessPdf" in request.url.params
    with pytest.raises(InvalidToolRequest) as exc_info:
        await client.search(SearchQuery(query="sleep"))
    assert S2_KEY not in caplog.text and S2_KEY not in str(exc_info.value)


async def test_s2_no_matches_returns_empty() -> None:
    result = await s2(Recorder(json_response(200, {"total": 0, "offset": 0}))).search(
        SearchQuery(query="sleep")
    )
    assert result.papers == []


@pytest.mark.parametrize(
    "response",
    [
        json_response(200, {"data": "oops"}),
        json_response(200, [1, 2]),
        httpx2.Response(200, text="nope"),
    ],
)
async def test_s2_malformed_responses(response: httpx2.Response) -> None:
    with pytest.raises(MalformedSourceResponse):
        await s2(Recorder(response)).search(SearchQuery(query="sleep"))


async def test_s2_timeout_and_rate_limit() -> None:
    with pytest.raises(SourceTimeout):
        await s2(Recorder(*[httpx2.ConnectTimeout("slow")] * 3)).search(SearchQuery(query="sleep"))

    clock = FakeClock()
    recorder = Recorder(
        json_response(429, {}), json_response(429, {}), json_response(200, {"data": [S2_ITEM]})
    )
    result = await s2(recorder, clock).search(SearchQuery(query="sleep"))
    assert len(result.papers) == 1 and clock.sleeps == [1.0, 2.0]  # no Retry-After → backoff
