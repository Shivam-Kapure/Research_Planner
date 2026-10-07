import uuid
from typing import ClassVar, Literal, Self

from pydantic import Field, model_validator

from app.schemas.contracts.common import Contract, ShortText, Strict, SubQuestionId, Text

ABSTRACT_ONLY_MAX_CONFIDENCE = 0.6

EvidenceBasis = Literal["full_text", "abstract_only", "metadata_only"]
Stance = Literal["supports", "refutes", "mixed", "neutral"]
FailureReason = Literal[
    "no_oa_pdf",
    "download_failed",
    "too_large",
    "malformed_pdf",
    "scanned_pdf",
    "extraction_error",
    "no_abstract",
]


class EvidenceItem(Strict):
    """One grounded claim from one paper; the unit of cross-paper comparison."""

    id: uuid.UUID
    paper_id: uuid.UUID
    sub_question_id: SubQuestionId
    claim: str = Field(min_length=1, max_length=400)
    stance: Stance
    quote: str = Field(min_length=1, max_length=600)  # verbatim from the source text
    location: str | None = Field(default=None, max_length=50)  # e.g. "p.4" or a section
    confidence: float = Field(ge=0, le=1)


class DocumentAnalysis(Contract):
    """Analysis → Synthesis; one per paper. Only quotes verified against the source remain;
    `ungrounded_dropped` records how many extracted items failed that check."""

    schema_name: ClassVar[str] = "document_analysis"

    paper_id: uuid.UUID
    basis: EvidenceBasis
    extraction_status: Literal["succeeded", "degraded", "failed"]
    failure_reason: FailureReason | None = None
    study_type: ShortText | None = None
    context: ShortText | None = None  # sample, population or setting
    methods_summary: Text | None = None
    key_findings: list[ShortText] = Field(default_factory=list, max_length=10)
    limitations: list[ShortText] = Field(default_factory=list, max_length=10)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=20)
    ungrounded_dropped: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if any(e.paper_id != self.paper_id for e in self.evidence):
            raise ValueError("evidence items must belong to the analysed paper")
        if len({e.id for e in self.evidence}) != len(self.evidence):
            raise ValueError("evidence ids must be unique")
        if self.basis == "metadata_only" and self.evidence:
            raise ValueError("metadata_only analyses cannot carry evidence")
        if self.basis == "abstract_only" and any(
            e.confidence > ABSTRACT_ONLY_MAX_CONFIDENCE for e in self.evidence
        ):
            raise ValueError(
                f"abstract_only confidence is capped at {ABSTRACT_ONLY_MAX_CONFIDENCE}"
            )
        if self.basis != "full_text" and self.failure_reason is None:
            raise ValueError("failure_reason is required when full text was not analysed")
        if self.extraction_status == "failed" and self.evidence:
            raise ValueError("failed extractions cannot carry evidence")
        return self


class EvidenceSet(Contract):
    """Snapshot assembled by Synthesis: which evidence answers which sub-question."""

    schema_name: ClassVar[str] = "evidence_set"

    iteration: int = Field(ge=1)
    by_sub_question: dict[SubQuestionId, list[uuid.UUID]]
    paper_count: int = Field(ge=0)
    full_text_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.full_text_count > self.paper_count:
            raise ValueError("full_text_count cannot exceed paper_count")
        for ids in self.by_sub_question.values():
            if len(ids) != len(set(ids)):
                raise ValueError("evidence ids must be unique within a sub-question")
        return self
