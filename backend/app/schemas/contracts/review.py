import re
import uuid
from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from app.schemas.contracts.common import Contract, ShortText, Strict

CitationKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_:\-]{1,64}$")]
_CITATION = re.compile(r"\[@([A-Za-z0-9_:\-]{1,64})\]")


def cited_keys(markdown: str) -> list[str]:
    return _CITATION.findall(markdown)


class ReviewSection(Strict):
    heading: ShortText
    kind: Literal["introduction", "body", "conclusion"] = "body"
    body_markdown: str = Field(min_length=1, max_length=12000)
    citation_keys: list[CitationKey] = Field(default_factory=list)
    evidence_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _citations_match_body(self) -> Self:
        if set(cited_keys(self.body_markdown)) != set(self.citation_keys):
            raise ValueError(f"citation_keys must match the [@key] citations in {self.heading!r}")
        if self.kind == "body" and not self.citation_keys:
            raise ValueError(f"body section {self.heading!r} must cite at least one paper")
        return self


class Reference(Strict):
    """Built by code from paper metadata, never written by the LLM."""

    citation_key: CitationKey
    paper_id: uuid.UUID
    title: str = Field(min_length=1, max_length=500)
    authors: list[ShortText] = Field(default_factory=list, max_length=10)
    year: int | None = Field(default=None, ge=1800, le=2100)
    doi: ShortText | None = None


class FinalReview(Contract):
    """Writer → API/UI."""

    schema_name: ClassVar[str] = "final_review"

    title: ShortText
    abstract: str = Field(min_length=1, max_length=3000)
    sections: list[ReviewSection] = Field(min_length=1, max_length=12)
    limitations: list[ShortText] = Field(default_factory=list, max_length=10)
    evidence_status: Literal["sufficient", "limited", "contradictory"]
    references: list[Reference] = Field(default_factory=list)

    @model_validator(mode="after")
    def _citations_resolve(self) -> Self:
        keys = [r.citation_key for r in self.references]
        if len(keys) != len(set(keys)):
            raise ValueError("reference citation keys must be unique")
        used = {k for s in self.sections for k in s.citation_keys}
        unknown = used - set(keys)
        if unknown:
            raise ValueError(f"citations without a reference: {sorted(unknown)}")
        if self.evidence_status != "sufficient" and not self.limitations:
            raise ValueError("limited or contradictory reviews must state their limitations")
        return self
