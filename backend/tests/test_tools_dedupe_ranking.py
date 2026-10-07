from typing import Any

import pytest

from app.tools.literature.dedupe import deduplicate
from app.tools.literature.models import normalize_title
from app.tools.literature.normalize import normalize_doi
from app.tools.literature.ranking import RankingWeights, filter_papers, rank_papers
from tests.tool_fakes import paper


@pytest.mark.parametrize(
    "raw",
    [
        "10.1000/ABC.123",
        " https://doi.org/10.1000/abc.123 ",
        "http://dx.doi.org/10.1000/abc.123",
        "doi:10.1000/ABC.123.",
        "DOI: 10.1000/abc.123",
    ],
)
def test_doi_normalisation(raw: str) -> None:
    assert normalize_doi(raw) == "10.1000/abc.123"


@pytest.mark.parametrize("raw", ["", "not a doi", "11.1000/abc", "10.1/x", None, 42])
def test_non_dois_are_rejected(raw: object) -> None:
    assert normalize_doi(raw) is None


def test_title_normalisation() -> None:
    assert normalize_title("  Sleep, Memory & Café: A Study! ") == "sleep memory cafe a study"


def test_same_doi_in_different_formats_merges_and_keeps_provenance() -> None:
    oa = paper(
        source="openalex", source_id="W1", doi="10.1000/abc", abstract="short", citation_count=5
    )
    s2 = paper(
        "Sleep deprivation impairs memory consolidation in adults.",
        source="semantic_scholar",
        source_id="s2a",
        rank=3,
        doi=normalize_doi("https://doi.org/10.1000/ABC"),
        abstract="Semantic Scholar abstract",
        citation_count=9,
        oa_pdf_url="https://arxiv.org/pdf/1",
    )
    result = deduplicate([oa, s2])
    assert result.duplicates_removed == 1 and len(result.papers) == 1
    merged = result.papers[0]
    assert [(s.source, s.source_id) for s in merged.sources] == [
        ("openalex", "W1"),
        ("semantic_scholar", "s2a"),
    ]
    assert merged.openalex_id == "W1" and merged.semantic_scholar_id == "s2a"
    assert merged.abstract == "Semantic Scholar abstract"  # S2 abstract preferred
    assert merged.citation_count == 9 and merged.oa_pdf_url == "https://arxiv.org/pdf/1"
    assert merged.paper_key == "doi:10.1000/abc"


def test_title_author_year_fallback_merges_when_no_doi() -> None:
    a = paper(source="openalex", source_id="W1", year=2020, authors=["Ana Smith"])
    b = paper(
        "SLEEP DEPRIVATION impairs memory-consolidation in adults",
        source="semantic_scholar",
        source_id="s2a",
        year=2020,
        authors=["A. Smith"],
    )
    assert len(deduplicate([a, b]).papers) == 1


@pytest.mark.parametrize(
    "other",
    [
        {"year": 2021, "authors": ["Ana Smith"]},  # different year
        {"year": 2020, "authors": ["Ben Jones"]},  # different first author
        {"year": 2020, "authors": []},  # cannot confirm the author
        {"year": None, "authors": ["Ana Smith"]},  # cannot confirm the year
    ],
)
def test_title_match_alone_is_not_enough(other: dict[str, Any]) -> None:
    a = paper(source="openalex", source_id="W1", year=2020, authors=["Ana Smith"])
    b = paper(source="semantic_scholar", source_id="s2a", **other)
    assert len(deduplicate([a, b]).papers) == 2


def test_similar_titles_and_conflicting_dois_are_kept_apart() -> None:
    a = paper(
        "Sleep deprivation impairs memory consolidation in adults",
        source_id="W1",
        year=2020,
        authors=["Ana Smith"],
    )
    b = paper(
        "Sleep deprivation impairs memory consolidation in older adults",
        source_id="W2",
        year=2020,
        authors=["Ana Smith"],
    )
    c = paper(
        source="semantic_scholar", source_id="s2c", doi="10.1/x", year=2020, authors=["Ana Smith"]
    )
    d = paper(
        source="semantic_scholar", source_id="s2d", doi="10.2/y", year=2020, authors=["Ana Smith"]
    )
    assert len(deduplicate([a, b]).papers) == 2
    assert len(deduplicate([c, d]).papers) == 2  # same title/author/year, different DOIs


def test_short_generic_titles_never_match_on_title() -> None:
    a = paper("Editorial", source_id="W1", year=2020, authors=["Ana Smith"])
    b = paper(
        "Editorial", source="semantic_scholar", source_id="s2", year=2020, authors=["Ana Smith"]
    )
    assert len(deduplicate([a, b]).papers) == 2


def test_dedupe_preserves_first_seen_order() -> None:
    papers = [paper(f"Distinct paper number {i} about sleep", source_id=f"W{i}") for i in range(5)]
    assert [p.openalex_id for p in deduplicate(papers).papers] == ["W0", "W1", "W2", "W3", "W4"]


def test_paper_id_is_deterministic() -> None:
    a = paper(doi="10.1000/abc")
    b = paper(
        "Another title entirely", source="semantic_scholar", source_id="zz", doi="10.1000/abc"
    )
    assert a.paper_id == b.paper_id


# ---------------- ranking ----------------


def test_ranking_is_deterministic_and_explained() -> None:
    papers = [
        paper("Old highly cited", source_id="W1", rank=2, year=1995, citation_count=5000),
        paper(
            "Recent open access",
            source_id="W2",
            rank=1,
            year=2024,
            citation_count=10,
            oa_pdf_url="https://repo.example/x.pdf",
            abstract="a",
            doi="10.9/z",
            authors=["A B"],
            venue="V",
        ),
        paper("No metadata at all", source_id="W3", rank=3),
    ]
    first = rank_papers(papers, current_year=2025)
    second = rank_papers(list(reversed(papers)), current_year=2025)
    assert [r.paper.openalex_id for r in first] == [r.paper.openalex_id for r in second]
    assert first[0].paper.openalex_id == "W2"
    assert first[-1].paper.openalex_id == "W3"
    bare = first[-1].signals
    assert bare["citations"] == bare["recency"] == bare["open_access"] == bare["completeness"] == 0
    assert set(first[0].signals) == {
        "relevance",
        "citations",
        "recency",
        "open_access",
        "completeness",
    }


def test_ranking_weights_change_order_transparently() -> None:
    old = paper("Old highly cited", source_id="W1", rank=2, year=1995, citation_count=5000)
    new = paper("Recent", source_id="W2", rank=2, year=2024, citation_count=1)
    by_citations = rank_papers(
        [new, old],
        current_year=2025,
        weights=RankingWeights(relevance=0, citations=1, recency=0, open_access=0, completeness=0),
    )
    by_recency = rank_papers(
        [new, old],
        current_year=2025,
        weights=RankingWeights(relevance=0, citations=0, recency=1, open_access=0, completeness=0),
    )
    assert by_citations[0].paper.openalex_id == "W1" and by_recency[0].paper.openalex_id == "W2"


def test_open_access_preference_breaks_otherwise_equal_papers() -> None:
    closed = paper("Paper without full text", source_id="W1")
    open_ = paper("Paper with full text", source_id="W2", oa_pdf_url="https://repo.example/a.pdf")
    assert rank_papers([closed, open_], current_year=2025)[0].paper.openalex_id == "W2"


def test_ties_are_broken_by_paper_key() -> None:
    a, b = paper("Same signals A", source_id="W9"), paper("Same signals B", source_id="W1")
    assert [r.paper.paper_key for r in rank_papers([a, b], current_year=2025)] == [
        "openalex:W1",
        "openalex:W9",
    ]


def test_filtering() -> None:
    papers = [
        paper(
            "In range with abstract",
            source_id="W1",
            year=2019,
            abstract="x",
            oa_pdf_url="https://r/a.pdf",
        ),
        paper("Too old", source_id="W2", year=2005, abstract="x"),
        paper("Unknown year", source_id="W3", abstract="x"),
        paper("No abstract", source_id="W4", year=2020),
    ]
    assert [p.openalex_id for p in filter_papers(papers, year_from=2010)] == ["W1", "W4"]
    assert [p.openalex_id for p in filter_papers(papers, require_abstract=True)] == [
        "W1",
        "W2",
        "W3",
    ]
    assert [p.openalex_id for p in filter_papers(papers, open_access_only=True)] == ["W1"]
