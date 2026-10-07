"""Deterministic paper deduplication.

Papers match only on exact keys, strongest first:
  1. DOI (normalised)
  2. provider ids (OpenAlex, Semantic Scholar, arXiv)
  3. normalised title + year + first author's surname, all three required.
There is no fuzzy matching: two papers with merely similar titles are never merged, and two
papers with different DOIs are never merged even if everything else matches.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.tools.literature.models import Paper, normalize_title

MIN_TITLE_WORDS_FOR_FALLBACK = 4  # "Introduction" or "Editorial" must not match on title alone


@dataclass(frozen=True)
class DedupeResult:
    papers: list[Paper]
    duplicates_removed: int


def match_keys(paper: Paper) -> list[str]:
    keys: list[str] = []
    if paper.doi:
        keys.append(f"doi:{paper.doi}")
    if paper.openalex_id:
        keys.append(f"openalex:{paper.openalex_id}")
    if paper.semantic_scholar_id:
        keys.append(f"s2:{paper.semantic_scholar_id}")
    if paper.arxiv_id:
        keys.append(f"arxiv:{paper.arxiv_id.lower()}")
    title = normalize_title(paper.title)
    surname = _first_author_surname(paper)
    if paper.year and surname and len(title.split()) >= MIN_TITLE_WORDS_FOR_FALLBACK:
        keys.append(f"title:{title}|{paper.year}|{surname}")
    return keys


def deduplicate(papers: Iterable[Paper]) -> DedupeResult:
    """Merge duplicates, keeping first-seen order (pass the primary source's results first)."""
    groups: list[Paper] = []
    index: dict[str, int] = {}
    seen = 0
    for paper in papers:
        seen += 1
        target = next(
            (
                index[key]
                for key in match_keys(paper)
                if key in index and _compatible(groups[index[key]], paper)
            ),
            None,
        )
        if target is None:
            groups.append(paper)
            target = len(groups) - 1
        else:
            groups[target] = merge(groups[target], paper)
        for key in match_keys(groups[target]):
            index.setdefault(key, target)
    return DedupeResult(groups, seen - len(groups))


def merge(primary: Paper, other: Paper) -> Paper:
    """Combine two records of one paper. The primary wins, except that Semantic Scholar's
    abstract is preferred (architecture §7). All provenance is kept."""
    known = {(s.source, s.source_id) for s in primary.sources}
    s2_abstract = next(
        (
            p.abstract
            for p in (primary, other)
            if p.abstract and any(s.source == "semantic_scholar" for s in p.sources)
        ),
        None,
    )
    counts = [c for c in (primary.citation_count, other.citation_count) if c is not None]
    return primary.model_copy(
        update={
            "authors": primary.authors or other.authors,
            "author_count": max(primary.author_count, other.author_count),
            "year": primary.year or other.year,
            "publication_date": primary.publication_date or other.publication_date,
            "abstract": s2_abstract or primary.abstract or other.abstract,
            "doi": primary.doi or other.doi,
            "openalex_id": primary.openalex_id or other.openalex_id,
            "semantic_scholar_id": primary.semantic_scholar_id or other.semantic_scholar_id,
            "arxiv_id": primary.arxiv_id or other.arxiv_id,
            "venue": primary.venue or other.venue,
            "citation_count": max(counts) if counts else None,
            "is_open_access": primary.is_open_access or other.is_open_access,
            "oa_pdf_url": primary.oa_pdf_url or other.oa_pdf_url,
            "landing_page_url": primary.landing_page_url or other.landing_page_url,
            "sources": [
                *primary.sources,
                *(s for s in other.sources if (s.source, s.source_id) not in known),
            ],
        }
    )


def _compatible(a: Paper, b: Paper) -> bool:
    return not (a.doi and b.doi and a.doi != b.doi)


def _first_author_surname(paper: Paper) -> str | None:
    if not paper.authors:
        return None
    words = normalize_title(paper.authors[0]).split()
    return words[-1] if words else None
