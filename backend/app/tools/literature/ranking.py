"""Transparent, deterministic ranking and filtering of candidate papers.

Each signal is scaled to 0..1 and reported alongside the weighted score, so a caller (or the
trace) can see exactly why a paper ranked where it did. The signals measure different things
and are not scientifically equivalent; the weights are a configurable heuristic for ordering
candidates before the Search Agent's own screening, not a quality judgement.
"""

import math
from collections.abc import Sequence
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.tools.literature.models import Paper

RECENCY_WINDOW_YEARS = 30


class RankingWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relevance: float = Field(default=0.45, ge=0, le=1)  # provider rank position
    citations: float = Field(default=0.2, ge=0, le=1)
    recency: float = Field(default=0.15, ge=0, le=1)
    open_access: float = Field(default=0.15, ge=0, le=1)
    completeness: float = Field(default=0.05, ge=0, le=1)


class RankedPaper(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paper: Paper
    score: float
    signals: dict[str, float]


def rank_papers(
    papers: Sequence[Paper],
    *,
    weights: RankingWeights | None = None,
    current_year: int | None = None,
) -> list[RankedPaper]:
    """Highest score first; ties are broken by paper_key so the order is fully deterministic."""
    weights = weights or RankingWeights()
    year_now = current_year or date.today().year
    max_citations = max((p.citation_count or 0 for p in papers), default=0)
    ranked = []
    for paper in papers:
        signals = {
            "relevance": max(1.0 / s.rank for s in paper.sources),  # reciprocal of best rank
            "citations": _citation_signal(paper.citation_count, max_citations),
            "recency": _recency_signal(paper.year, year_now),
            "open_access": 1.0 if paper.oa_pdf_url else 0.0,
            "completeness": _completeness(paper),
        }
        score = sum(getattr(weights, name) * value for name, value in signals.items())
        ranked.append(
            RankedPaper(
                paper=paper,
                score=round(score, 6),
                signals={k: round(v, 6) for k, v in signals.items()},
            )
        )
    return sorted(ranked, key=lambda r: (-r.score, r.paper.paper_key))


def filter_papers(
    papers: Sequence[Paper],
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    require_abstract: bool = False,
    open_access_only: bool = False,
) -> list[Paper]:
    """Keep papers that provably meet the constraints (an unknown year fails a year bound)."""

    def keep(p: Paper) -> bool:
        if (year_from or year_to) and p.year is None:
            return False
        if year_from and p.year is not None and p.year < year_from:
            return False
        if year_to and p.year is not None and p.year > year_to:
            return False
        if require_abstract and not p.abstract:
            return False
        return not (open_access_only and not p.oa_pdf_url)

    return [p for p in papers if keep(p)]


def _citation_signal(count: int | None, max_count: int) -> float:
    if not count or max_count <= 0:
        return 0.0
    return math.log1p(count) / math.log1p(max_count)


def _recency_signal(year: int | None, year_now: int) -> float:
    if year is None:
        return 0.0
    age = max(0, year_now - year)
    return max(0.0, 1.0 - age / RECENCY_WINDOW_YEARS)


def _completeness(paper: Paper) -> float:
    present = [paper.abstract, paper.doi, paper.year, paper.authors, paper.venue]
    return sum(1 for v in present if v) / len(present)
