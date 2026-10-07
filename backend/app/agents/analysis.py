"""Agent 3 — Document Analysis: selected papers → one DocumentAnalysis per paper.

Per paper: the Phase 5 document tools decide what text is legitimately available (full text,
abstract only, or nothing); the LLM extracts methodology, findings, limitations and evidence
claims; code then checks that every quote really occurs in the source (grounding) and drops
the rest. One paper failing never fails the iteration.
"""

import asyncio
import re
import time
import uuid
from dataclasses import dataclass

from pydantic import Field

from app.agents.base import Agent, as_json
from app.llm.errors import LLMError, NoProviderConfigured, ProviderAuthError
from app.llm.types import Message
from app.orchestration.runtime import BudgetExhausted
from app.orchestration.state import AgentFailure
from app.schemas.contracts import DocumentAnalysis, EvidenceItem, ResearchPlan
from app.schemas.contracts.analysis import ABSTRACT_ONLY_MAX_CONFIDENCE, Stance
from app.schemas.contracts.common import ShortText, Strict, SubQuestionId, Text
from app.schemas.contracts.search import CandidatePaper
from app.tools.documents.models import DocumentResult
from app.tools.documents.service import retrieve_document
from app.tools.literature.models import Paper

SYSTEM = """You are the Document Analysis agent of ResearchPilot. You read ONE paper and \
extract structured evidence for the research sub-questions. You do not search for papers and \
you do not synthesise across papers.

Report the study type, context (population/sample/setting/dataset), a methods summary, key \
findings and limitations. Then list evidence items (at most 8): each answers one sub-question \
with a claim, its stance (supports/refutes/mixed/neutral relative to the sub-question), a \
confidence 0-1, and a QUOTE COPIED VERBATIM from the text below (one or two sentences, no \
paraphrase) plus the page number shown in [page N] markers when available. Use only the text \
provided; if it does not address a sub-question, give no evidence for it."""

GROUNDING_RETRY = """These quotes do not appear verbatim in the text: {quotes}. Copy quotes \
exactly from the text (same words and order), or drop those evidence items."""

UNGROUNDED_RETRY_THRESHOLD = 0.5  # architecture §8: retry once if more than half are ungrounded


class ExtractedClaim(Strict):
    sub_question_id: SubQuestionId
    claim: str = Field(min_length=1, max_length=400)
    stance: Stance
    quote: str = Field(min_length=1, max_length=600)
    page: int | None = Field(default=None, ge=1)
    confidence: float = Field(ge=0, le=1)


class PaperExtraction(Strict):
    study_type: ShortText | None = None
    context: ShortText | None = None
    methods_summary: Text | None = None
    key_findings: list[ShortText] = Field(default_factory=list, max_length=10)
    limitations: list[ShortText] = Field(default_factory=list, max_length=10)
    evidence: list[ExtractedClaim] = Field(default_factory=list, max_length=8)


@dataclass(frozen=True)
class AnalysisOutcome:
    analyses: list[DocumentAnalysis]
    failures: list[AgentFailure]


class DocumentAnalysisAgent(Agent):
    node = "document_analysis"
    trace_agent = "analysis"
    role = "analysis"

    async def run(
        self,
        plan: ResearchPlan,
        selected: list[CandidatePaper],
        papers: dict[str, Paper],
        *,
        iteration: int,
        parent_id: uuid.UUID | None = None,
    ) -> AnalysisOutcome:
        gate = asyncio.Semaphore(self.rt.limits.analysis_concurrency)

        async def one(candidate: CandidatePaper) -> DocumentAnalysis | AgentFailure:
            async with gate:
                return await self._analyse_safely(
                    plan, papers[str(candidate.paper_id)], iteration, parent_id
                )

        results = await asyncio.gather(*(one(c) for c in selected))
        return AnalysisOutcome(
            analyses=[r for r in results if isinstance(r, DocumentAnalysis)],
            failures=[r for r in results if isinstance(r, AgentFailure)],
        )

    async def _analyse_safely(
        self, plan: ResearchPlan, paper: Paper, iteration: int, parent_id: uuid.UUID | None
    ) -> DocumentAnalysis | AgentFailure:
        try:
            return await self.analyse(plan, paper, iteration=iteration, parent_id=parent_id)
        except (NoProviderConfigured, ProviderAuthError, BudgetExhausted):
            raise  # run-level problems: not a per-paper failure
        except LLMError as exc:
            await self.rt.recorder.error(
                "analysis",
                iteration=iteration,
                code=exc.code,
                retryable=False,
                message=f"analysis of {paper.paper_key} failed: {exc.message}",
                parent_id=parent_id,
            )
            return AgentFailure(
                node=self.node,
                code=exc.code,
                message=exc.message[:300],
                iteration=iteration,
                paper_id=str(paper.paper_id),
            )

    async def analyse(
        self, plan: ResearchPlan, paper: Paper, *, iteration: int, parent_id: uuid.UUID | None
    ) -> DocumentAnalysis:
        started = time.perf_counter()
        document = await retrieve_document(paper, fetcher=self.rt.fetcher)
        await self.rt.recorder.tool_call(
            "analysis",
            iteration=iteration,
            name="retrieve_document",
            args={"paper_key": paper.paper_key, "has_oa_pdf": paper.oa_pdf_url is not None},
            result_summary=(
                f"mode={document.mode} reason={document.failure_reason} "
                f"pages={len(document.pages)} host={document.source_host}"
            ),
            status="ok" if document.mode == "full_text" else "warning",
            duration_ms=int((time.perf_counter() - started) * 1000),
            parent_id=parent_id,
        )
        if document.mode == "unavailable":
            # Nothing legitimately readable: record the paper without evidence, no LLM call.
            return DocumentAnalysis(
                paper_id=paper.paper_id,
                basis="metadata_only",
                extraction_status="failed",
                failure_reason=document.failure_reason or "no_abstract",
            )

        source_text, pages = _source(document, self.rt.limits.excerpt_chars)
        messages = [
            Message("system", SYSTEM),
            Message(
                "user",
                as_json(
                    {
                        "sub_questions": [sq.model_dump() for sq in plan.sub_questions],
                        "paper": {"title": paper.title, "year": paper.year, "venue": paper.venue},
                        "source_mode": document.mode,
                    }
                )
                + "\n\nTEXT:\n"
                + source_text,
            ),
        ]
        extraction = await self.llm(
            PaperExtraction,
            messages,
            iteration=iteration,
            parent_id=parent_id,
            max_output_tokens=900,
        )
        grounded, ungrounded = _ground(extraction, source_text, pages, plan)
        if (
            extraction.evidence
            and len(ungrounded) / len(extraction.evidence) > UNGROUNDED_RETRY_THRESHOLD
        ):
            messages += [
                Message("assistant", extraction.model_dump_json()),
                Message(
                    "user",
                    GROUNDING_RETRY.format(quotes=as_json([c.quote[:120] for c in ungrounded])),
                ),
            ]
            extraction = await self.llm(
                PaperExtraction,
                messages,
                iteration=iteration,
                parent_id=parent_id,
                max_output_tokens=900,
            )
            grounded, ungrounded = _ground(extraction, source_text, pages, plan)

        abstract_only = document.mode == "abstract_only"
        analysis = DocumentAnalysis(
            paper_id=paper.paper_id,
            basis="abstract_only" if abstract_only else "full_text",
            extraction_status="degraded" if abstract_only or ungrounded else "succeeded",
            failure_reason=document.failure_reason if abstract_only else None,
            study_type=extraction.study_type,
            context=extraction.context,
            methods_summary=extraction.methods_summary,
            key_findings=extraction.key_findings,
            limitations=extraction.limitations,
            evidence=[
                EvidenceItem(
                    id=uuid.uuid4(),
                    paper_id=paper.paper_id,
                    sub_question_id=claim.sub_question_id,
                    claim=claim.claim,
                    stance=claim.stance,
                    quote=claim.quote,
                    location=f"p.{page}" if page else ("abstract" if abstract_only else None),
                    confidence=min(claim.confidence, ABSTRACT_ONLY_MAX_CONFIDENCE)
                    if abstract_only
                    else claim.confidence,
                )
                for claim, page in grounded
            ],
            ungrounded_dropped=len(ungrounded),
        )
        await self.rt.recorder.validation(
            "analysis",
            iteration=iteration,
            schema_name="document_analysis",
            passed=not ungrounded,
            errors=[f"ungrounded quote dropped: {c.quote[:80]}" for c in ungrounded],
            dropped_items=len(ungrounded),
            parent_id=parent_id,
        )
        return analysis


def _source(document: DocumentResult, max_chars: int) -> tuple[str, list[tuple[int, str]]]:
    if document.mode == "full_text":
        pages = [(p.page_number, p.text) for p in document.excerpt(max_chars)]
        return "\n\n".join(f"[page {n}]\n{t}" for n, t in pages), pages
    abstract = document.abstract or ""
    return abstract, []


_WS = re.compile(r"\s+")
_QUOTE_CHARS = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})


def _norm(text: str) -> str:
    return _WS.sub(" ", text.translate(_QUOTE_CHARS)).strip().strip("\"'.…").lower()


def _ground(
    extraction: PaperExtraction, source: str, pages: list[tuple[int, str]], plan: ResearchPlan
) -> tuple[list[tuple[ExtractedClaim, int | None]], list[ExtractedClaim]]:
    """Keep claims whose quote occurs verbatim (whitespace/case/quote-mark normalised) in the
    source and whose sub-question exists; locate the page from the source text itself."""
    haystack = _norm(source)
    grounded: list[tuple[ExtractedClaim, int | None]] = []
    ungrounded: list[ExtractedClaim] = []
    for claim in extraction.evidence:
        quote = _norm(claim.quote)
        if (
            claim.sub_question_id not in plan.sub_question_ids
            or len(quote) < 12
            or quote not in haystack
        ):
            ungrounded.append(claim)
            continue
        page = next((n for n, text in pages if quote in _norm(text)), None)
        grounded.append((claim, page))
    return grounded, ungrounded
