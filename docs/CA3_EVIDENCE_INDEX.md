# CA3 Evidence Index

Each requirement is mapped to evidence that exists in this repository or was verified in production. "REAL" means produced by the live system with real LLMs and literature APIs. "AUTOMATED" means tests using scripted LLMs and mocked HTTP, against real PostgreSQL.

| Requirement | Evidence | Location | Explanation |
|---|---|---|---|
| ≥ 4 distinct agents | Five agent classes | `backend/app/agents/{planner,search,analysis,synthesis,writer}.py` | Each has its own prompt, LLM schema and output contract; `base.py` is shared plumbing only |
| Clear responsibilities | Agent table | [FINAL_ARCHITECTURE §4](FINAL_ARCHITECTURE.md#4-agent-responsibilities), [PHASE6_MULTI_AGENT.md](PHASE6_MULTI_AGENT.md) | Input, reasoning, tools, output, handoff and adaptation per agent |
| Planning | `ResearchPlan` (sub-questions, priorities, strategy, criteria) | `backend/app/agents/planner.py`, `schemas/contracts/planning.py` | Plan v+1 with `revision_reason` on a scope revision |
| Reasoning | LLM verdict + deterministic validator | `agents/synthesis.py`, `orchestration/validation.py` | The validator can override the LLM; overrides are traced |
| Tool use | Literature search, deduplication/ranking, safe PDF retrieval and extraction | `backend/app/tools/` | Called by Search and Analysis; every call is a `tool_call` trace event |
| Inter-agent communication | Nine versioned contracts | `backend/app/schemas/contracts/`, [FINAL_ARCHITECTURE §5](FINAL_ARCHITECTURE.md#5-inter-agent-communication-structured-contracts) | Typed handoffs through LangGraph state; `handoff` events in the trace |
| Orchestration | LangGraph `StateGraph` with conditional edges | `backend/app/orchestration/{graph,routing,state,runner}.py` | Pure route functions after synthesis and replanning |
| Adaptive replanning: insufficient → search revision | **REAL** | `docs/traces/2026-10-07_run-34908068.json`, `docs/traces/2026-10-07_run-d29bb92b.json`; production run `9403b69c` | `34908068`: then the budget limit. `d29bb92b`: then **sufficient**. `9403b69c`: two revisions, then the iteration limit |
| Adaptive replanning: contradictory → scope revision | **AUTOMATED** only | `backend/tests/test_research_graph.py` | Scripted graph run reaches plan v2. No real run has produced a contradictory verdict |
| Bounded execution | Iteration, call, token, time and recursion limits | `orchestration/runtime.py` (`ResearchLimits`, `RunBudget`), `routing.py` | **REAL**: `34908068` stopped at `budget_limit` and `9403b69c` at `iteration_limit` |
| Validation | Contract validators, quote grounding, citation checks, validator override | `schemas/contracts/*.py`, `agents/analysis.py`, `agents/writer.py` | `validation` events in every real trace (ungrounded quotes dropped, overrides) |
| Error handling | Retries, fallbacks, abstract fallback, partial/failed states, cancel, interrupt sweep | [FINAL_ARCHITECTURE §17](FINAL_ARCHITECTURE.md#17-error-handling) | **REAL**: 429 retries and 3–5 fallbacks per real trace; failed (`accaccc5`) and partial (`769ca6b8`, `531f100b`) local runs, documented in [PHASE7_RUNS_API.md](PHASE7_RUNS_API.md#first-real-runs-2026-10-07-utc-local-development-stack) |
| Real execution traces | Unedited API exports | `docs/traces/*.json` (125 and 120 events) | Agent starts and completions, LLM calls, tool calls, validations, decisions, replans and handoffs |
| Live trace in the product | Run timeline built from trace events | `frontend/src/lib/trace/timeline.ts`, `frontend/src/components/agents/` | Shown for the production run `9403b69c` |
| Automated tests | pytest **388 passed**; frontend `npm test` **40 passed** | `backend/tests/`, `frontend/tests/` | Run in Phase 10 (see PROJECT_STATE "Phase 10 Validation") |
| Security | Argon2id, sessions, encrypted keys, redaction, origin check, SSRF guard | `app/services/`, `app/core/security.py`, `app/tools/documents/pdf.py` | Production checks: cookie flags, 403 for foreign origins, HSTS, isolation 404s |
| Deployment | Vercel + Render + Neon | [README](../README.md#production-deployment-free-tiers), [FINAL_ARCHITECTURE §15](FINAL_ARCHITECTURE.md#15-deployment-architecture) | https://researchpilot-rho.vercel.app; `/healthz` and `/readyz` returned 200 |
| Production verification | Auth, isolation, run, security scan | PROJECT_STATE "Phase 9 Validation" | Production run `9403b69c` is recorded from the UI (owner-only data; not exported) |
| Clean repository structure | `backend/`, `frontend/`, `docs/`, CI | repository root | No secrets (gitleaks clean), `.env` files ignored |
| Incremental development | 13 commits, one per phase plus fixes | `git log` | Phases 0–9; all commits are authored by one team account (see PROJECT_STATE "Open Items") |
| Architecture and data flow | Diagram, state flow, contracts | [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md), [PHASE1_ARCHITECTURE.md](PHASE1_ARCHITECTURE.md) | The original design plus the final as-built document |
| Screenshots | **TO CAPTURE** | [SCREENSHOT_CHECKLIST.md](SCREENSHOT_CHECKLIST.md) | None are committed yet |
| Demo | Demo guide and talking points | [DEMO_GUIDE.md](DEMO_GUIDE.md), [DEMO_TALKING_POINTS.md](DEMO_TALKING_POINTS.md) | — |
