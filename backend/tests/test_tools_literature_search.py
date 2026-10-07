import pytest

from app.tools.errors import LiteratureUnavailable, SourceUnavailable
from app.tools.literature.models import ProviderSearchResult, SearchQuery
from app.tools.literature.search import LiteratureSearchService
from tests.tool_fakes import paper

pytestmark = pytest.mark.anyio

QUERY = SearchQuery(query="sleep memory")


class FakeSource:
    def __init__(self, source: str, result: ProviderSearchResult | Exception) -> None:
        self.source = source
        self.result = result
        self.calls = 0

    async def search(self, query: SearchQuery) -> ProviderSearchResult:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def oa_result(*papers: object) -> ProviderSearchResult:
    return ProviderSearchResult(source="openalex", papers=list(papers), total_available=100)


def s2_result(*papers: object) -> ProviderSearchResult:
    return ProviderSearchResult(source="semantic_scholar", papers=list(papers))


async def test_combines_both_sources_and_deduplicates() -> None:
    shared_oa = paper(source_id="W1", doi="10.1/shared")
    shared_s2 = paper(source="semantic_scholar", source_id="s1", doi="10.1/shared", rank=2)
    only_s2 = paper(
        "A Semantic Scholar only paper on sleep", source="semantic_scholar", source_id="s2"
    )
    service = LiteratureSearchService(
        {
            "openalex": FakeSource("openalex", oa_result(shared_oa)),
            "semantic_scholar": FakeSource("semantic_scholar", s2_result(shared_s2, only_s2)),
        }
    )
    result = await service.search(QUERY)

    assert result.candidates_total == 3 and result.duplicates_removed == 1
    assert [p.paper_key for p in result.papers] == ["doi:10.1/shared", "s2:s2"]  # OpenAlex first
    assert {s.source for s in result.papers[0].sources} == {"openalex", "semantic_scholar"}
    assert [(o.source, o.status, o.result_count) for o in result.outcomes] == [
        ("openalex", "ok", 1),
        ("semantic_scholar", "ok", 2),
    ]
    assert result.degraded_sources == []


async def test_one_failed_source_degrades_instead_of_failing() -> None:
    service = LiteratureSearchService(
        {
            "openalex": FakeSource("openalex", oa_result(paper())),
            "semantic_scholar": FakeSource(
                "semantic_scholar", SourceUnavailable("semantic_scholar", "503")
            ),
        }
    )
    result = await service.search(QUERY)
    assert len(result.papers) == 1
    assert result.degraded_sources == ["semantic_scholar"]
    assert result.outcomes[1].error_code == "source_unavailable"


async def test_all_sources_failing_raises_literature_unavailable() -> None:
    service = LiteratureSearchService(
        {
            "openalex": FakeSource("openalex", SourceUnavailable("openalex", "503")),
            "semantic_scholar": FakeSource(
                "semantic_scholar", SourceUnavailable("semantic_scholar", "503")
            ),
        }
    )
    with pytest.raises(LiteratureUnavailable) as exc_info:
        await service.search(QUERY)
    assert exc_info.value.code == "literature_unavailable"


async def test_source_selection_and_unconfigured_sources() -> None:
    oa = FakeSource("openalex", oa_result(paper()))
    service = LiteratureSearchService({"openalex": oa})
    result = await service.search(QUERY)  # semantic scholar not configured
    assert [(o.source, o.status) for o in result.outcomes] == [
        ("openalex", "ok"),
        ("semantic_scholar", "skipped"),
    ]

    only_s2 = await service.search(QUERY, sources=["openalex"])
    assert [o.source for o in only_s2.outcomes] == ["openalex"] and oa.calls == 2

    with pytest.raises(LiteratureUnavailable):
        await service.search(QUERY, sources=["semantic_scholar"])


async def test_combined_results_are_capped() -> None:
    many_oa = oa_result(
        *[paper(f"OpenAlex distinct sleep paper {i}", source_id=f"W{i}") for i in range(25)]
    )
    many_s2 = s2_result(
        *[
            paper(
                f"Semantic Scholar distinct paper {i}", source="semantic_scholar", source_id=f"s{i}"
            )
            for i in range(25)
        ]
    )
    service = LiteratureSearchService(
        {
            "openalex": FakeSource("openalex", many_oa),
            "semantic_scholar": FakeSource("semantic_scholar", many_s2),
        }
    )
    assert len((await service.search(QUERY)).papers) == 40  # hard cap
    assert len((await service.search(QUERY, max_results=6)).papers) == 6
    assert (
        len((await service.search(QUERY, max_results=500)).papers) == 40
    )  # callers cannot raise it
