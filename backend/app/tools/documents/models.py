import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.contracts.analysis import FailureReason

SourceMode = Literal["full_text", "abstract_only", "unavailable"]

# ~4k tokens ≈ 16k characters: the per-paper budget for Document Analysis (architecture §6.1).
DEFAULT_EXCERPT_CHARS = 16_000
_BACK_MATTER = re.compile(
    r"^\s*(references|bibliography|works cited|literature cited)\s*:?\s*$", re.I | re.M
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PageText(_Strict):
    page_number: int = Field(ge=1)  # 1-based, as printed in citations ("p.4")
    text: str


class DocumentResult(_Strict):
    """What the Document Analysis Agent receives for one paper. The source mode is explicit,
    and page numbers are kept so evidence can be grounded to a page later."""

    paper_key: str
    mode: SourceMode
    failure_reason: FailureReason | None = None  # why full text was not used
    error_code: str | None = None  # tool error code, for the trace
    detail: str | None = Field(default=None, max_length=300)  # safe, host-level detail
    pages: list[PageText] = Field(default_factory=list)
    page_count: int | None = Field(default=None, ge=0)  # pages in the PDF (≥ pages read)
    truncated: bool = False
    abstract: str | None = None
    source_host: str | None = None  # never the full URL (could carry tokens)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.mode == "full_text":
            if not self.pages or self.failure_reason is not None:
                raise ValueError("full_text results need pages and no failure_reason")
        else:
            if self.failure_reason is None:
                raise ValueError(f"{self.mode} results must state a failure_reason")
            if self.pages:
                raise ValueError(f"{self.mode} results cannot carry pages")
        if self.mode == "abstract_only" and not self.abstract:
            raise ValueError("abstract_only results need an abstract")
        return self

    def excerpt(self, max_chars: int = DEFAULT_EXCERPT_CHARS) -> list[PageText]:
        """Page-aware text within a character budget, stopping at the reference list."""
        selected: list[PageText] = []
        remaining = max_chars
        for page in self.pages:
            text = page.text
            back_matter = _BACK_MATTER.search(text)
            if back_matter and page.page_number > 1:
                text = text[: back_matter.start()].rstrip()
            if text:
                selected.append(PageText(page_number=page.page_number, text=text[:remaining]))
                remaining -= len(selected[-1].text)
            if back_matter or remaining <= 0:
                break
        return selected
