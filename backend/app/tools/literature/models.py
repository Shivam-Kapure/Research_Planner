"""Provider-neutral literature contracts. Agents consume these, never raw provider JSON."""

import hashlib
import re
import unicodedata
import uuid
from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

Source = Literal["openalex", "semantic_scholar"]
SOURCES: tuple[Source, ...] = ("openalex", "semantic_scholar")

# Per-call bounds enforced by the tools themselves, whatever the caller asks for.
MAX_RESULTS_PER_SOURCE = 25
MAX_PAGE = 3
MAX_COMBINED_RESULTS = 40  # the screening step reads at most 40 candidates (architecture §6.1)
MAX_AUTHORS = 10
MAX_ABSTRACT_CHARS = 5000
MAX_TITLE_CHARS = 500

_PAPER_NAMESPACE = uuid.UUID("6f3c1a52-2d0e-4c8b-9a61-5b7e0f4d2c19")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_title(title: str) -> str:
    """Case-, accent-, punctuation- and whitespace-insensitive form used for matching."""
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return _NON_ALNUM.sub(" ", folded).strip()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SearchQuery(_Strict):
    query: str = Field(min_length=2, max_length=300)
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    open_access_only: bool = False
    limit: int = Field(default=10, ge=1, le=MAX_RESULTS_PER_SOURCE)
    page: int = Field(default=1, ge=1, le=MAX_PAGE)

    @model_validator(mode="after")
    def _years(self) -> Self:
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from must not be after year_to")
        return self


class SourceRef(_Strict):
    """Provenance: where a paper was found and how the provider ranked it."""

    source: Source
    source_id: str = Field(min_length=1, max_length=200)
    rank: int = Field(ge=1)  # 1-based position in that provider's results
    relevance_score: float | None = None  # provider-specific scale; not comparable across sources
    url: str | None = Field(default=None, max_length=2000)


class Paper(_Strict):
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    authors: list[str] = Field(default_factory=list, max_length=MAX_AUTHORS)
    author_count: int = Field(default=0, ge=0)
    year: int | None = Field(default=None, ge=1500, le=2100)
    publication_date: date | None = None
    abstract: str | None = Field(default=None, max_length=MAX_ABSTRACT_CHARS)
    doi: str | None = Field(default=None, max_length=300)  # normalised: lower-case, no URL prefix
    openalex_id: str | None = None
    semantic_scholar_id: str | None = None
    arxiv_id: str | None = None
    venue: str | None = Field(default=None, max_length=300)
    citation_count: int | None = Field(default=None, ge=0)
    is_open_access: bool = False
    oa_pdf_url: str | None = Field(default=None, max_length=2000)
    landing_page_url: str | None = Field(default=None, max_length=2000)
    sources: list[SourceRef] = Field(min_length=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def paper_key(self) -> str:
        """Stable identifier from the strongest available id (DOI first)."""
        if self.doi:
            return f"doi:{self.doi}"
        if self.openalex_id:
            return f"openalex:{self.openalex_id}"
        if self.semantic_scholar_id:
            return f"s2:{self.semantic_scholar_id}"
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id.lower()}"
        digest = hashlib.sha256(f"{normalize_title(self.title)}|{self.year}".encode()).hexdigest()
        return f"title:{digest[:16]}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def paper_id(self) -> uuid.UUID:
        """Deterministic UUID for the same paper_key (used by the agent contracts)."""
        return uuid.uuid5(_PAPER_NAMESPACE, self.paper_key)


class SourceOutcome(_Strict):
    source: Source
    status: Literal["ok", "failed", "skipped"]
    result_count: int = Field(default=0, ge=0)
    total_available: int | None = Field(default=None, ge=0)
    error_code: str | None = None


class ProviderSearchResult(_Strict):
    source: Source
    papers: list[Paper] = Field(max_length=MAX_RESULTS_PER_SOURCE)
    total_available: int | None = Field(default=None, ge=0)


class LiteratureSearchResult(_Strict):
    """Combined, deduplicated result of one search request across sources."""

    query: SearchQuery
    papers: list[Paper] = Field(max_length=MAX_COMBINED_RESULTS)
    outcomes: list[SourceOutcome]
    candidates_total: int = Field(ge=0)  # before deduplication and the combined cap
    duplicates_removed: int = Field(ge=0)

    @property
    def degraded_sources(self) -> list[Source]:
        return [o.source for o in self.outcomes if o.status == "failed"]
