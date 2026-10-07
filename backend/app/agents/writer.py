"""Agent 5 — Review Writer: accumulated research state → FinalReview.

The LLM writes the prose; code owns everything that must be exact: citation keys come only
from analysed papers, references are built from paper metadata (never written by the LLM),
evidence_status follows the validated decision, and limitations always state why research
stopped when it was not sufficient.
"""

import re
import uuid

from pydantic import Field, ValidationError

from app.agents.base import Agent, as_json
from app.llm.types import Message
from app.orchestration.routing import StopReason
from app.schemas.contracts import (
    DocumentAnalysis,
    FinalReview,
    ResearchPlan,
    ResearchRequest,
    SynthesisDecision,
)
from app.schemas.contracts.common import ShortText, Strict
from app.schemas.contracts.review import Reference, ReviewSection, cited_keys
from app.tools.literature.models import Paper

SYSTEM = """You are the Review Writer agent of ResearchPilot. You write the final structured \
literature review from the evidence the other agents gathered. You do not search, analyse \
papers or change the verdict.

Rules:
- Use only the evidence provided. Cite papers inline as [@KEY] using exactly the keys given \
(e.g. [@P1]); never invent keys or references.
- Sections: an "introduction", one or more "body" sections (each must cite at least one paper; \
organise them by theme or sub-question), and a "conclusion".
- Be explicit about uncertainty. If evidence_status is "limited" or "contradictory", say so in \
the abstract and list concrete limitations (missing sub-questions, contradictions, \
abstract-only evidence, iteration or budget limits).
- If no papers are available, write only an introduction and a conclusion explaining that no \
usable evidence was found."""

CITATION_RETRY = """These citation keys do not exist: {keys}. Use only: {allowed}. Body \
sections must cite at least one existing key."""

_UNKNOWN_CITATION = re.compile(r"\[@([A-Za-z0-9_:\-]{1,64})\]")


class SectionDraft(Strict):
    heading: ShortText
    kind: str = Field(pattern=r"^(introduction|body|conclusion)$")
    body_markdown: str = Field(min_length=1, max_length=12000)


class ReviewDraft(Strict):
    title: ShortText
    abstract: str = Field(min_length=1, max_length=3000)
    sections: list[SectionDraft] = Field(min_length=1, max_length=12)
    limitations: list[ShortText] = Field(default_factory=list, max_length=10)


class ReviewWriterAgent(Agent):
    node = "review_writer"
    trace_agent = "writer"
    role = "writer"
    writer_budget = True

    async def run(
        self,
        request: ResearchRequest,
        plan: ResearchPlan,
        decision: SynthesisDecision | None,
        analyses: list[DocumentAnalysis],
        papers: dict[str, Paper],
        *,
        iteration: int,
        stop_reason: StopReason | None,
        parent_id: uuid.UUID | None = None,
    ) -> FinalReview:
        keys = _citation_keys(analyses)
        status = _evidence_status(decision, stop_reason)
        system_limits = _system_limitations(decision, stop_reason, analyses, iteration)
        messages = [
            Message("system", SYSTEM),
            Message(
                "user",
                as_json(
                    {
                        "question": request.question,
                        "plan": {
                            "objective": plan.objective,
                            "sub_questions": [sq.model_dump() for sq in plan.sub_questions],
                        },
                        "evidence_status": status,
                        "stop_reason": stop_reason,
                        "known_limitations": system_limits,
                        "final_synthesis": decision.model_dump(mode="json") if decision else None,
                        "papers": [
                            _paper_entry(key, papers.get(str(pid)), analyses, pid)
                            for pid, key in keys.items()
                        ],
                    }
                ),
            ),
        ]
        allowed = set(keys.values())
        for attempt in range(2):
            draft = await self.llm(
                ReviewDraft,
                messages,
                iteration=iteration,
                parent_id=parent_id,
                max_output_tokens=3500,
            )
            unknown = sorted(
                {k for s in draft.sections for k in cited_keys(s.body_markdown)} - allowed
            )
            try:
                if unknown:
                    raise ValueError(f"unknown citation keys {unknown}")
                review = _assemble(draft, keys, papers, status, system_limits)
            except (ValueError, ValidationError) as exc:
                await self.rt.recorder.validation(
                    "writer",
                    iteration=iteration,
                    schema_name="final_review",
                    passed=False,
                    errors=[str(exc)[:300]],
                    parent_id=parent_id,
                )
                if attempt == 1:
                    raise
                messages += [
                    Message("assistant", draft.model_dump_json()),
                    Message(
                        "user",
                        CITATION_RETRY.format(keys=unknown or "none", allowed=sorted(allowed)),
                    ),
                ]
                continue
            await self.rt.recorder.validation(
                "writer",
                iteration=iteration,
                schema_name="final_review",
                passed=True,
                parent_id=parent_id,
            )
            return review
        raise AssertionError("unreachable")  # pragma: no cover


def _citation_keys(analyses: list[DocumentAnalysis]) -> dict[uuid.UUID, str]:
    """P1, P2, … for papers that contributed evidence, in the order they were analysed."""
    keys: dict[uuid.UUID, str] = {}
    for a in analyses:
        if a.evidence and a.paper_id not in keys:
            keys[a.paper_id] = f"P{len(keys) + 1}"
    return keys


def _evidence_status(decision: SynthesisDecision | None, stop_reason: StopReason | None) -> str:
    if decision and decision.verdict == "sufficient" and stop_reason == "sufficient":
        return "sufficient"
    if decision and decision.verdict == "contradictory":
        return "contradictory"
    return "limited"


def _system_limitations(
    decision: SynthesisDecision | None,
    stop_reason: StopReason | None,
    analyses: list[DocumentAnalysis],
    iteration: int,
) -> list[str]:
    notes: list[str] = []
    if stop_reason == "iteration_limit":
        notes.append(
            f"Research stopped at the iteration limit ({iteration}) "
            "before the evidence was sufficient."
        )
    elif stop_reason == "budget_limit":
        notes.append("Research stopped early to stay within the free-tier LLM budget.")
    if decision:
        for c in decision.coverage:
            if c.status != "covered":
                notes.append(
                    f"Sub-question {c.sub_question_id} is {c.status} "
                    f"({c.supporting_papers} paper(s))."
                )
        for conflict in decision.contradictions:
            if not conflict.resolved:
                notes.append(f"Unresolved contradiction on {conflict.sub_question_id}.")
    abstract_only = sum(1 for a in analyses if a.basis == "abstract_only" and a.evidence)
    if abstract_only:
        notes.append(f"{abstract_only} paper(s) were analysed from the abstract only.")
    return [n[:300] for n in notes][:10]


def _paper_entry(
    key: str, paper: Paper | None, analyses: list[DocumentAnalysis], pid: uuid.UUID
) -> dict[str, object]:
    evidence = [e for a in analyses if a.paper_id == pid for e in a.evidence]
    return {
        "key": key,
        "title": paper.title if paper else "",
        "year": paper.year if paper else None,
        "evidence": [
            {
                "sub_question_id": e.sub_question_id,
                "stance": e.stance,
                "claim": e.claim,
                "location": e.location,
            }
            for e in evidence
        ],
    }


def _assemble(
    draft: ReviewDraft,
    keys: dict[uuid.UUID, str],
    papers: dict[str, Paper],
    status: str,
    system_limits: list[str],
) -> FinalReview:
    by_key = {v: k for k, v in keys.items()}
    sections = []
    for s in draft.sections:
        cited = list(dict.fromkeys(cited_keys(s.body_markdown)))
        sections.append(
            ReviewSection(
                heading=s.heading,
                kind=s.kind,
                body_markdown=s.body_markdown,
                citation_keys=cited,
            )
        )
    used = list(dict.fromkeys(k for s in sections for k in s.citation_keys))
    references = []
    for key in used:
        paper = papers.get(str(by_key[key]))
        if paper is None:
            raise ValueError(f"no metadata for {key}")
        references.append(
            Reference(
                citation_key=key,
                paper_id=paper.paper_id,
                title=paper.title,
                authors=paper.authors,
                year=paper.year,
                doi=paper.doi,
            )
        )
    limitations = list(dict.fromkeys(system_limits + list(draft.limitations)))[:10]
    return FinalReview(
        title=draft.title,
        abstract=draft.abstract,
        sections=sections,
        limitations=limitations,
        evidence_status=status,
        references=references,
    )
