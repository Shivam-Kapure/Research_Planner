"""Versioned inter-agent contracts (architecture §9)."""

from app.schemas.contracts.analysis import DocumentAnalysis, EvidenceItem, EvidenceSet
from app.schemas.contracts.common import AgentName, Contract
from app.schemas.contracts.planning import ResearchPlan, ResearchRequest, SubQuestion
from app.schemas.contracts.review import FinalReview, Reference, ReviewSection
from app.schemas.contracts.search import CandidatePaper, SearchRequest, SearchResults
from app.schemas.contracts.synthesis import ReplanningRequest, SynthesisDecision

CONTRACTS: tuple[type[Contract], ...] = (
    ResearchRequest,
    ResearchPlan,
    SearchRequest,
    SearchResults,
    DocumentAnalysis,
    EvidenceSet,
    SynthesisDecision,
    ReplanningRequest,
    FinalReview,
)

__all__ = [
    "CONTRACTS",
    "AgentName",
    "CandidatePaper",
    "Contract",
    "DocumentAnalysis",
    "EvidenceItem",
    "EvidenceSet",
    "FinalReview",
    "Reference",
    "ReplanningRequest",
    "ResearchPlan",
    "ResearchRequest",
    "ReviewSection",
    "SearchRequest",
    "SearchResults",
    "SubQuestion",
    "SynthesisDecision",
]
