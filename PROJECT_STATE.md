# Project State — ResearchPilot

**Multi-Agent AI Research & Literature Review System**

## Team: Decepticons

| Member | PRN |
|---|---|
| Gaud Kashyup Pawan | 23070122114 |
| Kapure Shivam Sahebrao | 23070122113 |
| Kisna Kanti | 23070122116 |
| Harsh Ledwani | 23070122100 |

## Purpose

ResearchPilot takes a research question and produces an academic literature review. Five specialised agents coordinate to do this. They plan the research, search for and analyse literature, synthesise the evidence, and write the review. The system is meant to be genuinely agentic rather than a fixed pipeline. Agents reason, use tools, exchange structured messages, validate their outputs and adapt their plan when the evidence requires it.

## Agents

| # | Agent | Responsibility |
|---|---|---|
| 1 | Research Planner | Breaks the research question into sub-questions, search strategy and scope/inclusion criteria. |
| 2 | Literature Search | Runs searches with tools against literature sources and returns candidate papers. |
| 3 | Document Analysis | Extracts methods, findings, claims and limitations from the retrieved documents. |
| 4 | Evidence Synthesis | Groups and compares the evidence and finds gaps or contradictions. Decides whether the evidence is sufficient. |
| 5 | Review Writer | Writes the final structured, cited literature review. |

## Required Adaptive Behaviour

```
Planning → Search → Analysis → Synthesis
  ├─ evidence insufficient/contradictory → request additional/revised research
  │     → Search → Analysis → Synthesis (repeat, bounded)
  └─ evidence sufficient → Review Writer
```

The Evidence Synthesis Agent must be able to trigger this replanning loop. The system must also support agent reasoning, tool use, structured inter-agent communication, validation and error handling.

## Known Infrastructure Requirements

- Database: Neon PostgreSQL
- Frontend hosting: Vercel
- Backend hosting: Railway or Render
- LLM providers: user-provided Groq and Gemini API keys, supplied after authentication (never stored in the repo)
- Frontend: a polished, intentionally designed research product (visual inspiration will be provided in the frontend phase)

## CA3 Evidence Required

At least 4 distinct agents, clear responsibilities, planning/reasoning/tool use/adaptation, inter-agent coordination, adaptive replanning, architecture and data-flow docs, precise I/O definitions, robust error handling, real automated tests, clean repo structure, meaningful incremental commits, real execution traces of agent handoffs.

## Current Phase

**Phase 1 complete: architecture and technology selection.** No application code exists yet. Full design: [docs/PHASE1_ARCHITECTURE.md](docs/PHASE1_ARCHITECTURE.md).

**Next:** Phase 2, Foundation.

## Phase 1 Decisions

- **Orchestration:** LangGraph `StateGraph` (no LangChain model wrappers). Routing is driven by agent outputs. The Evidence Synthesis Agent emits a `ReplanningRequest`, which routes to Search (search revision) or the Planner (scope revision). Bounded at 3 research iterations.
- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async + asyncpg, Alembic, httpx, uv. Runs execute as in-process background tasks, and the UI polls for progress.
- **Frontend:** Next.js (App Router) + TypeScript + Tailwind, TanStack Query, OpenAPI-generated types. The API is accessed same-origin through a Vercel rewrite proxy.
- **Database:** Neon PostgreSQL. Relational tables plus JSONB `agent_outputs`. PDFs, full text and decrypted keys stay transient.
- **Auth:** backend-owned email/password (Argon2id) with opaque DB sessions in an httpOnly cookie.
- **User API keys:** encrypted with MultiFernet, write-only, validated on save, and kept out of graph state, traces and logs.
- **LLM:** own `LLMProvider` protocol (Groq, Gemini), configured per agent role with fallback.
- **Literature:** OpenAlex (primary) + Semantic Scholar (secondary).
- **PDF:** pypdf, with abstract-only fallback and quote-grounding validation.
- **Trace:** own append-only `trace_events` table, exportable as JSON. Only traces from real runs are kept.
- **Tests:** pytest/respx/scripted LLM/real Postgres; Vitest + RTL; one Playwright smoke test. CI on GitHub Actions.
- **Deploy:** Vercel Hobby (frontend) + Render Free (backend) + Neon Free (DB). Docker only for the backend image and local Postgres. The frontend handles Render cold starts with a waking state and a readiness check.
- **LLM budget:** at most 3 iterations, 6 papers per iteration and 15 per run, 60 LLM calls and 200k tokens per run, per-provider rate limiting. Model IDs are configurable free-tier candidates.

## Hard Cost Constraint

Free tiers and free access only: Vercel Hobby, Render Free, Neon Free, free-tier Groq/Gemini keys (Groq only, Gemini only, or both), and free OpenAlex/Semantic Scholar access. No paid plan, billing-enabled API or paid subscription may be required, and no service is to be upgraded. Free-tier limits apply and are documented in the architecture doc.

## Open Items (team input)

- Per-member ownership split.

## Implementation Phases

2. Foundation: repo skeleton, FastAPI and Next.js scaffolds, CI, local Postgres
3. Database, auth and encrypted credentials
4. Agent contracts, LLM provider layer and trace recorder
5. Tools: OpenAlex, Semantic Scholar, dedupe, PDF
6. Agents, LangGraph orchestration and replanning
7. Runs API, end-to-end tests and first real trace
8. Frontend
9. Deployment
10. Final documentation and demo
