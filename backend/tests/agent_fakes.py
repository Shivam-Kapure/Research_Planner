"""Deterministic test doubles for Phase 6. Real agents, real graph, real tools and real trace
recorder; only the LLM provider and the literature source are scripted (no network, no keys)."""

import asyncio
import json
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
from fastapi import FastAPI

from app.llm.gateway import LLMGateway
from app.llm.types import LLMRequest, LLMResponse, ProviderName, TokenUsage
from app.orchestration.runtime import ResearchLimits, ResearchRuntime
from app.services.trace_recorder import TraceRecorder
from app.tools.documents.pdf import SafePdfFetcher
from app.tools.literature.models import Paper, ProviderSearchResult, SearchQuery, SourceRef
from app.tools.literature.search import LiteratureSearchService
from tests.conftest import create_run, execute
from tests.llm_fakes import FakeClock
from tests.tool_fakes import public_resolver

PAPER_PDF = (Path(__file__).parent / "fixtures" / "pdf" / "paper.pdf").read_bytes()
Reply = str | Exception | Callable[[LLMRequest], str]


def schema_title(request: LLMRequest) -> str:
    """The gateway's first system message states the JSON Schema of the requested output."""
    text = request.messages[0].content
    return str(json.loads(text.split("JSON Schema:\n", 1)[1])["title"])


def user_json(request: LLMRequest) -> Any:
    """The structured context an agent sent (the JSON part of the last user message)."""
    content = [m for m in request.messages if m.role == "user"][0].content
    return json.loads(content.split("\n\nTEXT:\n", 1)[0])


def source_text(request: LLMRequest) -> str:
    content = [m for m in request.messages if m.role == "user"][0].content
    return content.split("\n\nTEXT:\n", 1)[1]


class ScriptedLLM:
    """LLMProvider whose reply is chosen by the requested output schema. Each schema has a
    queue of replies; the last reply repeats. Replies may be callables of the request, so
    content-dependent answers (e.g. quotes from the paper being analysed) stay deterministic
    even when agents call the LLM concurrently."""

    def __init__(self, scripts: dict[str, list[Reply]], name: ProviderName = "groq") -> None:
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self._name = name
        self.calls: list[str] = []

    @property
    def name(self) -> ProviderName:
        return self._name

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            self.reply(request), self._name, request.model, TokenUsage(200, 80), latency_ms=3
        )

    def reply(self, request: LLMRequest) -> str:
        title = schema_title(request)
        self.calls.append(title)
        queue = self.scripts[title]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item(request) if callable(item) else item


# ---------------------------------------------------------------- scripted agent behaviour

SQ1 = "Does sleep deprivation impair memory consolidation in adults?"
SQ2 = "Which sleep stages matter most for memory consolidation?"


def plan_reply(request: LLMRequest | None = None, *, extra_sq: str | None = None) -> str:
    sub_questions = [
        {"id": "sq-1", "text": SQ1, "rationale": "Core question", "priority": 1},
        {"id": "sq-2", "text": SQ2, "rationale": "Mechanism", "priority": 2},
    ]
    if extra_sq:
        sub_questions[0]["text"] = extra_sq
    return json.dumps(
        {
            "plan_version": 1,
            "objective": "Assess how sleep deprivation affects memory consolidation in adults.",
            "sub_questions": sub_questions,
            "search_strategy": "Keyword queries on OpenAlex and Semantic Scholar for experiments.",
            "inclusion_criteria": ["Human participants"],
            "exclusion_criteria": ["Animal-only studies"],
            "keywords": [
                "sleep deprivation",
                "memory consolidation",
                "sleep stages",
                "older adults",
            ],
        }
    )


def revised_plan_reply(request: LLMRequest) -> str:
    return plan_reply(
        extra_sq="Does sleep deprivation impair memory consolidation in older adults?"
    )


def query_reply(request: LLMRequest) -> str:
    """Initial, revised and refined query plans, chosen by what the agent was told."""
    system = " ".join(m.content for m in request.messages if m.role == "system")
    context = user_json(request)
    if "returned too few new candidates" in system:
        queries = {"sq-1": ["unmatched alternative terminology"]}
    elif "SEARCH REVISION" in system:
        queries = {"sq-2": ["slow wave sleep memory"]}
    elif context.get("plan", {}).get("plan_version", 1) > 1:
        queries = {"sq-1": ["older adults sleep memory"]}
    else:
        queries = {"sq-1": ["sleep deprivation memory"]}
    return json.dumps(
        {
            "targets": [{"sub_question_id": k, "queries": v} for k, v in queries.items()],
            "rationale": "Short keyword queries per sub-question.",
        }
    )


def screen_all(request: LLMRequest) -> str:
    candidates = user_json(request)["candidates"]
    return json.dumps(
        {
            "decisions": [
                {
                    "index": c["index"],
                    "include": True,
                    "relevance": 0.9 - 0.01 * c["index"],
                    "sub_question_ids": ["sq-1", "sq-2"],
                    "reason": "Directly relevant",
                }
                for c in candidates
            ]
        }
    )


_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")


def extract_two_claims(request: LLMRequest) -> str:
    """Quote two real sentences from the text the agent supplied (one per sub-question)."""
    title = user_json(request)["paper"]["title"]
    if "Broken" in title:
        return "this is not JSON"
    sentences = [
        s.strip()
        for s in _SENTENCE.split(source_text(request))
        if len(s.strip()) >= 30 and not s.startswith("[page")
    ]
    evidence = [
        {
            "sub_question_id": sq,
            "claim": f"Claim about {sq} from {title}",
            "stance": "supports",
            "quote": sentence,
            "page": None,
            "confidence": 0.8,
        }
        for sq, sentence in zip(("sq-1", "sq-2"), sentences, strict=False)
    ]
    return json.dumps(
        {
            "study_type": "Randomised crossover study",
            "context": "Healthy adults",
            "methods_summary": "Word-pair learning with and without sleep.",
            "key_findings": ["Recall was lower after sleep deprivation"],
            "limitations": ["Small sample"],
            "evidence": evidence,
        }
    )


def synthesis_reply(
    verdict: str, *, replanning: dict[str, Any] | None = None, contradict: bool = False
) -> Callable[[LLMRequest], str]:
    def reply(request: LLMRequest) -> str:
        evidence = [e for e in user_json(request)["evidence"] if e["sub_question_id"] == "sq-1"]
        contradictions = []
        if contradict and len(evidence) >= 2:
            contradictions = [
                {
                    "sub_question_id": "sq-1",
                    "claim_a": evidence[0]["id"],
                    "claim_b": evidence[1]["id"],
                    "explanation": "Opposite effects reported for older adults",
                    "resolved": False,
                }
            ]
        themes = (
            [
                {
                    "title": "Recall",
                    "summary": "Recall drops after sleep loss.",
                    "evidence_ids": [evidence[0]["id"]],
                }
            ]
            if evidence
            else []
        )
        return json.dumps(
            {
                "verdict": verdict,
                "rationale": f"Scripted verdict: {verdict}.",
                "themes": themes,
                "contradictions": contradictions,
                "replanning": replanning,
            }
        )

    return reply


SEARCH_REVISION = {
    "kind": "search_revision",
    "directives": [
        {"sub_question_id": "sq-2", "suggested_queries": ["sleep stages memory consolidation"]},
        {
            "sub_question_id": "sq-1",
            "suggested_queries": ["sleep deprivation recall meta-analysis"],
        },
    ],
}
SCOPE_REVISION = {
    "kind": "scope_revision",
    "scope_change": "Split sq-1 by age group: older adults.",
}


def write_review(request: LLMRequest) -> str:
    context = user_json(request)
    keys = [p["key"] for p in context["papers"]]
    sections = [
        {"heading": "Introduction", "kind": "introduction", "body_markdown": "Why sleep matters."}
    ]
    if keys:
        sections.append(
            {
                "heading": "Findings",
                "kind": "body",
                "body_markdown": "Sleep loss impairs recall "
                + " ".join(f"[@{k}]" for k in keys[:3])
                + ".",
            }
        )
    sections.append(
        {"heading": "Conclusion", "kind": "conclusion", "body_markdown": "More research is needed."}
    )
    return json.dumps(
        {
            "title": "Sleep deprivation and memory consolidation",
            "abstract": f"Evidence status: {context['evidence_status']}.",
            "sections": sections,
            "limitations": [],
        }
    )


def scripts(synthesis: list[Reply], **overrides: list[Reply]) -> dict[str, list[Reply]]:
    base: dict[str, list[Reply]] = {
        "ResearchPlan": [plan_reply],
        "QueryPlan": [query_reply],
        "Screening": [screen_all],
        "PaperExtraction": [extract_two_claims],
        "SynthesisDraft": synthesis,
        "ReviewDraft": [write_review],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- literature + documents


def make_paper(key: str, title: str, *, pdf: bool = True, abstract: str | None = None) -> Paper:
    return Paper(
        title=title,
        authors=["Ana Smith"],
        author_count=1,
        year=2021,
        abstract=abstract,
        openalex_id=key,
        is_open_access=pdf,
        oa_pdf_url=f"https://repo.example.org/{key}.pdf" if pdf else None,
        sources=[SourceRef(source="openalex", source_id=key, rank=1)],
    )


ABSTRACT = (
    "Older adults showed a smaller recall deficit after one night of sleep loss. "
    "Slow wave sleep duration predicted overnight retention of word pairs."
)


class CatalogSource:
    """A literature source whose results depend only on the query text."""

    source = "openalex"

    def __init__(self, catalog: Callable[[str], list[Paper]]) -> None:
        self.catalog = catalog
        self.queries: list[str] = []

    async def search(self, query: SearchQuery) -> ProviderSearchResult:
        self.queries.append(query.query)
        papers = self.catalog(query.query)[: query.limit]
        return ProviderSearchResult(source="openalex", papers=papers, total_available=len(papers))


def pdf_server(missing: set[str] = frozenset()) -> httpx2.AsyncClient:  # type: ignore[assignment]
    """Serves the real fixture PDF for every repo URL except the `missing` keys (404)."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        key = request.url.path.rsplit("/", 1)[-1].removesuffix(".pdf")
        if key in missing:
            return httpx2.Response(404)
        return httpx2.Response(200, content=PAPER_PDF, headers={"content-type": "application/pdf"})

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


async def make_user(app: FastAPI) -> uuid.UUID:
    user_id = uuid.uuid4()
    await execute(
        app,
        "INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')",
        id=user_id,
        email=f"{user_id}@example.com",
    )
    return user_id


async def make_runtime(
    app: FastAPI,
    llm: ScriptedLLM,
    catalog: Callable[[str], list[Paper]],
    *,
    missing_pdfs: set[str] = frozenset(),  # type: ignore[assignment]
    limits: ResearchLimits | None = None,
    gateway: LLMGateway | None = None,
) -> tuple[ResearchRuntime, CatalogSource]:
    source = CatalogSource(catalog)
    user_id = await make_user(app)
    runtime = ResearchRuntime(
        gateway=gateway
        or LLMGateway({"groq": llm}, {"groq": ["scripted-model"]}, sleep=FakeClock().sleep),
        literature=LiteratureSearchService({"openalex": source}),
        fetcher=SafePdfFetcher(pdf_server(missing_pdfs), resolver=public_resolver),
        recorder=TraceRecorder(
            app.state.database.sessionmaker, run_id=await create_run(app, user_id), user_id=user_id
        ),
        limits=limits or ResearchLimits(),
    )
    return runtime, source


async def trace_rows(app: FastAPI, run_id: uuid.UUID) -> list[dict[str, Any]]:
    from sqlalchemy import text

    async with app.state.database.engine.connect() as conn:
        result = await conn.execute(
            text("SELECT row_to_json(t)::text FROM trace_events t WHERE run_id = :r ORDER BY seq"),
            {"r": run_id},
        )
        return [json.loads(row[0]) for row in result]


# ---------------------------------------------------------------- Runs API helpers


class GatedLLM(ScriptedLLM):
    """A ScriptedLLM that waits for `gate` before answering, to observe queued/running states."""

    def __init__(self, scripts: dict[str, list[Reply]], gate: "asyncio.Event") -> None:
        super().__init__(scripts)
        self.gate = gate

    async def generate(self, request: LLMRequest) -> LLMResponse:
        await self.gate.wait()
        return await super().generate(request)


def install_executor(
    app: FastAPI,
    llm: ScriptedLLM | None,
    catalog: Callable[[str], list[Paper]],
    *,
    missing_pdfs: set[str] = frozenset(),  # type: ignore[assignment]
    gateway_factory: Any = None,
    max_concurrent: int = 1,
    limits: ResearchLimits | None = None,
) -> CatalogSource:
    """Replace the app's run executor with one wired to scripted test doubles."""
    from app.services.runs import RunExecutor

    source = CatalogSource(catalog)

    async def scripted_gateway(db: Any, user_id: uuid.UUID) -> LLMGateway:
        if llm is None:
            return LLMGateway({}, {"groq": ["scripted-model"]})
        return LLMGateway({"groq": llm}, {"groq": ["scripted-model"]}, sleep=FakeClock().sleep)

    app.state.run_executor = RunExecutor(
        app.state.database.sessionmaker,
        gateway_factory=gateway_factory or scripted_gateway,
        literature=LiteratureSearchService({"openalex": source}),
        fetcher=SafePdfFetcher(pdf_server(missing_pdfs), resolver=public_resolver),
        max_concurrent=max_concurrent,
        limits=limits,
    )
    return source


async def wait_for_run(
    client: Any, run_id: str, *, until: tuple[str, ...] | None = None, timeout_s: float = 30
) -> dict[str, Any]:
    """Poll GET /api/runs/{id} (as a client would) until it reaches one of `until`."""
    import asyncio as _asyncio

    from app.schemas.api.runs import TERMINAL_STATUSES

    wanted = until or TERMINAL_STATUSES
    deadline = _asyncio.get_running_loop().time() + timeout_s
    while True:
        body: dict[str, Any] = (await client.get(f"/api/runs/{run_id}")).json()
        if body["status"] in wanted:
            return body
        if _asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"run stuck in {body['status']}")
        await _asyncio.sleep(0.02)
