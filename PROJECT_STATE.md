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

- Database: Neon PostgreSQL (Free)
- Frontend hosting: Vercel Hobby
- Backend hosting: Render Free
- LLM providers: user-provided Groq and Gemini API keys, supplied after authentication (never stored in the repo)
- Frontend: a polished, intentionally designed research product (visual inspiration will be provided in the frontend phase)

## CA3 Evidence Required

At least 4 distinct agents, clear responsibilities, planning/reasoning/tool use/adaptation, inter-agent coordination, adaptive replanning, architecture and data-flow docs, precise I/O definitions, robust error handling, real automated tests, clean repo structure, meaningful incremental commits, real execution traces of agent handoffs.

## Current Phase

**Phase 7 complete: Runs API, persistence, and the first real end-to-end run.**
- The Phase 6 graph now runs behind an authenticated Runs API, with persisted runs, agent outputs and traces.
- One real free-tier run succeeded (`completed_with_limitations`) and its trace is exported unedited to `docs/traces/`.
- No frontend or deployment yet.
- Design: [docs/PHASE1_ARCHITECTURE.md](docs/PHASE1_ARCHITECTURE.md), [docs/PHASE6_MULTI_AGENT.md](docs/PHASE6_MULTI_AGENT.md), [docs/PHASE7_RUNS_API.md](docs/PHASE7_RUNS_API.md).

**Next:** Phase 8, the frontend. Visual inspiration is the editorial restraint of lujoliving.com: typography, whitespace, large sections and storytelling. That's for style only; no content, branding or assets are copied.

## Phase 7: What Was Added

- **Database** (migration `0003`):
  - `runs` (status check constraint, progress counters, safe error JSONB, index on user + created_at).
  - `agent_outputs` (contract JSON per agent and iteration; cascades with its run).
  - `trace_events.run_id` FK → `runs` with ON DELETE CASCADE, added **NOT VALID** so trace rows from before Phase 7 are kept while new rows are enforced. The append-only trigger is unchanged.
- **Runs API** (`app/api/runs.py`, `app/schemas/api/runs.py`):
  - `POST /api/runs` returns 202 and runs in the background; one active run per user.
  - `GET /api/runs` paginates.
  - `GET /api/runs/{id}`, `/events?after=&limit=`, `/outputs`, `/result` (409 while running), and `POST /{id}/cancel`.
  - Ownership: another user's run returns 404; unauthenticated requests return 401.
- **Execution** (`app/services/runs.py`):
  - `RunExecutor` runs the same Phase 6 `run_research()` in in-process asyncio tasks behind a semaphore (`MAX_CONCURRENT_RUNS`, default 1).
  - `DbRunSink` persists each agent's contracts as soon as the node finishes, links them to the trace via `output_ref`, updates progress, and marks a key `invalid` when the provider rejects it.
  - On startup, runs left queued or running are marked `failed: interrupted`.
  - The budget is never reset by replanning.
- **Graph integration:**
  - `traced()` persists outputs and progress through an optional `RunSink` on `ResearchRuntime`.
  - Validation errors are summarised without echoing model output.
  - The agent base reports rejected credentials.
- **Credentials:** `PUT /api/credentials/{provider}` checks the key with one model-list call (`valid`/`invalid`/`unverified`); `VALIDATE_CREDENTIALS_ON_SAVE`.
- **App wiring:**
  - One shared `httpx2` client and one literature service (shared Semantic Scholar pacing).
  - Lifespan sweep and shutdown.
  - Startup still needs no LLM key.
- **Provider controls** found necessary in the live runs: `GROQ_REASONING_EFFORT` (gpt-oss) and `GEMINI_THINKING_LEVEL` (Gemini 3.x).
- **Fixes from real runs, each with a regression test:**
  - The Writer's retry now feeds back the actual validation problem.
  - The citation rule is stated in the Writer's output-schema description, because `gemini-3.5-flash-lite` ignored the prompt-only instruction.
  - The Writer always states a limitation when no synthesis exists.
  - Quote grounding now folds Unicode hyphens and non-breaking spaces.
  - pypdf's warnings were silenced in logs.

## Phase 7 Validation (actually run, 2026-10-08)

- **Backend CI sequence, run locally:** `uv lock --check`, `uv sync --locked`, ruff check, ruff format --check and mypy (strict) all pass. **pytest: 388 passed** (23 new) against real PostgreSQL 17, covering:
  - API end-to-end runs through the real graph, including the **adaptive insufficient → search_revision → sufficient** path
  - ownership (detail, result, trace, outputs, cancel, list)
  - the lifecycle queued → running → completed with bounded concurrency
  - failed (no provider), partial (Writer failure), completed_with_limitations (iteration limit), cancel, and the startup sweep
  - pagination, run-delete cascade through the append-only trace, key checks on save, provider 401 → key marked invalid
  - no secrets in the `runs`, `agent_outputs` and trace tables or in API responses
- **Mutation check:** removing the user filter from `get_owned` made the ownership test fail. It was restored.
- **Migration 0003:** verified on a database that already held a trace row for a run that didn't exist. The row was kept and the FK was `NOT VALID`; a new orphan row was rejected; `alembic check` reported no drift; downgrade 0002 and re-upgrade both worked.
- **Real runs** (local stack, the user's free-tier Groq + Gemini keys entered through a hidden prompt into the credentials API; the keys never appeared in chat, files or logs). There were four genuine attempts; all are kept in the database and documented in PHASE7_RUNS_API.md:
  - `accaccc5`: **failed**, which exposed the model configuration issues.
  - `769ca6b8` and `531f100b`: **partial**, which exposed the Writer issues.
  - **`34908068-3832-4445-9f2f-8911e9414b93`: `completed_with_limitations`.** Path: planner → search → analysis → synthesis(insufficient) → replanning(search_revision) → search → analysis → synthesis(insufficient) → limit_reached(budget_limit) → writer. The run had 125 trace events, 48 LLM calls (80k tokens), 12 literature searches and 12 document retrievals (4 full text), and produced a 4-section review with 7 references.
- **Secret scan of the real run:** both provider keys, the session cookie, the password hash and the encryption key were absent from the DB tables, API responses and server logs.

## Phase 6: What Was Added

- **Agents** (`backend/app/agents/`): five distinct classes, each with its own prompt, LLM output schema and Phase 4 contract.
  - `PlannerAgent`: request → `ResearchPlan`. Handles scope revision using the `ReplanningRequest`; the version is set by code.
  - `LiteratureSearchAgent`: plan → LLM query plan → Phase 5 search tools → at most one LLM refinement → one batched LLM screening → `SearchResults`. Search revisions run the synthesis directives first and exclude papers already seen.
  - `DocumentAnalysisAgent`: for each paper, Phase 5 retrieval (full text, abstract or nothing) → LLM extraction → **quote grounding** (with one retry) → `DocumentAnalysis`. A failing paper is isolated.
  - `EvidenceSynthesisAgent`: code computes coverage → the LLM proposes a verdict, themes, contradictions and replanning → the **deterministic validator** accepts or overrides → `SynthesisDecision` + a `ReplanningRequest` that is checked against the decision.
  - `ReviewWriterAgent`: accumulated state → `FinalReview`. Citations are `[@Pn]` keys only, and references are built from metadata. Limitations are listed whenever evidence is not sufficient. Invented citation keys get one retry.
  - `agents/base.py`: shared plumbing only — gateway calls with traced provider fallback (≤ 3 candidates), budget checks, and an `llm_call` trace for every attempt, failed ones included.
- **Orchestration** (`backend/app/orchestration/`):
  - `graph.py`: a LangGraph `StateGraph` with the nodes planner, literature_search, document_analysis, evidence_synthesis, replanning and review_writer, and conditional edges after synthesis (writer / replanning / limit_reached) and after replanning (search_revision / scope_revision).
  - `state.py`: typed `ResearchState` holding research data only, with append-only reducers.
  - `routing.py`: pure route functions.
  - `validation.py`: `SufficiencyRules`, `compute_coverage` and `validate_verdict`.
  - `runtime.py`: `ResearchRuntime` (gateway, tools, recorder — secrets stay here, not in state), `ResearchLimits` and `RunBudget`.
  - `runner.py`: `run_research()` traces `run_started`/`run_completed`, applies the recursion limit (40) and the run timeout (20 min), and returns a structured final state (`completed`, `completed_with_limitations`, `partial` or `failed`).
- **Phase 4 change (additive):** `LLMError.attempts` now carries the attempt records made before a failure, so failed LLM calls are traced too.
- **Dependency:** `langgraph>=1.2.14,<1.3` (1.2.14 resolved). It pulls in transitive packages including `langchain-core` and the `langsmith` client library. LangSmith is **not used**, needs no account, and is off unless `LANGSMITH_TRACING` is set, which this project never does. No existing package versions changed.
- **Docs:** `docs/PHASE6_MULTI_AGENT.md`.

## Phase 6 Validation (actually run, 2026-10-08)

- **Backend CI sequence, run locally:** `uv lock --check`, `uv sync --locked`, ruff check, ruff format --check and mypy (strict) all pass. **pytest: 365 passed** (42 new) against real PostgreSQL 17.
- **Real graph executions** (`tests/test_research_graph.py`), with the trace checked event by event:
  - **planner → search → analysis → synthesis(insufficient) → replanning(search_revision) → search → analysis → synthesis(sufficient) → writer**. One PDF returned 404 and that paper was analysed from its abstract.
  - **contradictory → scope_revision → planner (plan v2) → search → analysis → synthesis(sufficient) → writer**.
  - iteration limit: 3 syntheses and 2 replans → `limit_reached` → a review marked `limited`, with a limitations entry for the iteration limit.
  - an LLM "sufficient" that the validator overrode to insufficient, after which the loop continued.
  - a per-paper failure that did not stop the run.
  - a fatal no-provider error, recorded as a structured `failed` state.
  - gap-free, parented trace sequences.
- **Per-agent tests** (`tests/test_agents.py`) cover each agent alone, the validator matrix, coverage and routing.
- **Secrets** (`tests/test_research_secrets.py`): a real encrypted Groq key goes through the real adapter over a mock transport. The key appears in the Authorization header only, never in the pickled state or the trace rows.
- **Mutation checks:** I temporarily made routing never replan, made the validator never override, and made Search ignore the directives. 13 tests failed, and all three changes were reverted.
- **Manual inspection:** printed the trace of a real adaptive run (62 events) and confirmed the agent order, verdicts, routes and iteration labels.

## Phase 5: What Was Added (`backend/app/tools/`, deterministic, no LLM)

- **Literature** (`tools/literature/`):
  - **Contracts:** typed models `SearchQuery`, `Paper`, `SourceRef`, `ProviderSearchResult`, `LiteratureSearchResult` and `SourceOutcome`.
    - `Paper` carries `paper_key`, taken from the strongest available ID: DOI, then OpenAlex, then Semantic Scholar, then arXiv, then a title hash.
    - It also carries a deterministic `paper_id`, a UUID5 of `paper_key`, for the agent contracts.
  - **Clients:** `OpenAlexClient` (`/works`) and `SemanticScholarClient` (`/graph/v1/paper/search`).
    - They use async `httpx2`, a 20 s timeout, and a cap of 2 MB per response.
    - At most 2 retries on timeout, 5xx or 429, honouring `Retry-After` up to 30 s; 4xx errors are never retried.
    - Responses are normalised defensively.
    - Credentials are all optional and free: OpenAlex mailto and API key, and the Semantic Scholar `x-api-key` header. The Semantic Scholar client paces itself with a rate limiter.
  - **Bounds per call:** ≤ 25 results per source, page ≤ 3, ≤ 40 combined.
  - **`LiteratureSearchService`:** queries both sources in parallel with OpenAlex first, then deduplicates and caps. If one source fails the result is marked degraded; if every source fails it raises `LiteratureUnavailable`.
  - **`dedupe.py`:** exact keys only — DOI (normalised), then provider IDs, then title + year + first-author surname, which needs a title of at least 4 words. Papers with conflicting DOIs are never merged, and there is no fuzzy matching. Merges keep the provenance of every source and prefer the Semantic Scholar abstract.
  - **`ranking.py`:** a weighted, explained score from reciprocal provider rank, log citations, recency over 30 years, open-access PDF and metadata completeness, with ties broken by `paper_key`. `filter_papers` filters by year, abstract and open access.
- **Documents** (`tools/documents/`):
  - **`oa.py`:** only provider-reported open-access PDF URLs are used.
  - **`pdf.py` (`SafePdfFetcher`):**
    - SSRF guards on every hop: http(s) on default ports only, no userinfo, internal hostnames refused, and every DNS answer must be a public IP. Loopback, private, link-local/metadata (169.254.169.254), CGNAT, ULA and IPv4-mapped addresses are blocked.
    - At most 3 manually validated redirects, with no https → http downgrade.
    - The content type must be a PDF type, and `%PDF-` must appear in the first 1 KB.
    - Downloads are streamed with a **15 MB** cap (checked against the declared length and while reading) and a 30 s overall deadline.
    - PDFs are held in memory only; no temporary files are created.
  - **`extraction.py`:** pypdf runs in a worker thread with a 20 s deadline. Limits are ≤ 40 pages, 8k characters per page and 120k characters in total, with page numbers preserved. Encrypted or malformed PDFs fail as `InvalidPdf`. Fewer than 200 characters per page on average counts as `scanned_pdf`.
  - **`service.retrieve_document(paper)`:** returns a `DocumentResult` with mode `full_text`, `abstract_only` or `unavailable`. Its `failure_reason` uses the Phase 4 `DocumentAnalysis` vocabulary, and it records the tool `error_code` and host. It never raises for document problems. `excerpt()` returns about 16k characters, page-numbered, stopping at the reference list.
  - **`errors.py`:** structured tool errors with safe messages (host and status only). They are raised outside `except` blocks, so they carry no request context.
- **Security hardening:**
  - Log records from `httpx2` drop URL query strings, which can hold the OpenAlex `api_key`, signed-URL tokens or the mailto address.
  - The Phase 4 trace sanitiser now also redacts credential query parameters (`api_key`, `token`, `signature`, …) and treats `x-api-key` as a sensitive key. This was strengthened, not weakened.
- **Fixtures:** `tests/fixtures/pdf/build_fixtures.py` deterministically builds `paper.pdf` (4 pages with a text layer, including a reference list) and `scanned.pdf` (3 text-less pages). A test checks that the committed files match the builder.
- **Dependency added:** `pypdf` 6.19 (BSD). No other services or infrastructure were added, and there is no cache.

## Phase 5 Validation (actually run, 2026-10-08)

- **Backend CI sequence, run locally:** `uv lock --check`, `uv sync --locked`, ruff check, ruff format --check and mypy (strict) all pass. **pytest: 323 passed** (123 new) against real PostgreSQL 17. `alembic check` reports no drift; there was no schema change.
- **Tool tests:** all use `httpx2.MockTransport` and local PDF fixtures, with no network access. They include real pypdf extraction of the fixtures, the SSRF matrix (22 blocked destinations plus 5 redirect targets), size, signature and timeout limits, and the fallback reasons.
- **Mutation checks:** I temporarily disabled three controls:
  - redirect re-validation
  - URL-query log redaction
  - the streamed 15 MB cap

  The tests failed for each, and all three were restored.
- **Docker image:** builds (469 MB), imports the tools and pypdf, and `/readyz` returns 200. `docker compose config` is valid.
- **gitleaks CLI 8.30.1:** git history and all 121 to-be-committed files are clean.
- **Manual live smoke test** (not automated, no keys used):
  - OpenAlex returned and normalised 5 results.
  - Semantic Scholar, without a key, was rate-limited (429) after the bounded retries, so the service correctly degraded to OpenAlex-only.
  - One real open-access PDF was fetched and all 8 pages were extracted, with the 16k-character excerpt applied.
- **Not run:** GitHub Actions (only runs after a push) and the frontend (unchanged).

## Phase 4: What Was Added

- **Contracts** (`app/schemas/contracts/`, architecture §9):
  - The contracts are `ResearchRequest`, `ResearchPlan`, `SearchRequest`, `SearchResults`, `DocumentAnalysis` (with `EvidenceItem`), `EvidenceSet`, `SynthesisDecision`, `ReplanningRequest` and `FinalReview`.
  - They are Pydantic v2 models: immutable, rejecting unknown fields, and carrying a `schema_name` plus a serialised `schema_version`. `canonical_json()` serialises them deterministically.
  - Validation is built in:
    - plan consistency, with a priority-1 sub-question and a revision reason required from version 2
    - selected + rejected ≤ total, and unique papers
    - evidence belongs to its paper, and abstract-only confidence is capped at 0.6
    - the coverage rule from §12 (`coverage_status`) and verdict consistency
    - `search_revision` / `scope_revision` requirements, and `ReplanningRequest.check_against(decision)`
    - review citations must resolve to references
  - Contracts carry no secrets and no database or provider fields. ResearchPlan gained a `search_strategy` field, which the Phase 4 spec required.
- **LLM layer** (`app/llm/`):
  - `LLMProvider` protocol, with Groq and Gemini REST adapters running on `httpx2` (now a runtime dependency). Groq uses the OpenAI-compatible chat completions API with a Bearer header. Gemini uses `generateContent` with the `x-goog-api-key` header, never the URL.
  - `LLMGateway` is the single entry point:
    - `generate_structured(schema, …)` adds a provider-neutral JSON instruction, requests JSON mode, validates with Pydantic, and allows one repair round that feeds back field errors without the submitted values.
    - Transient retries are capped at 2 with 1 s / 2 s backoff, honouring `Retry-After` up to 60 s.
    - Per-provider, per-key-owner RPM pacing.
    - Role preferences: Groq for planner, search and analysis; Gemini for synthesis and writer. A role falls back to whichever provider exists.
  - Errors are classified as `auth_failed`, `invalid_request`, `rate_limited`, `daily_quota_exhausted`, `timeout`, `provider_unavailable`, `bad_response`, `content_blocked`, `malformed_output`, `structured_output_invalid` and `no_provider_configured`.
  - `build_gateway_for_user()` reads the user's keys through the Phase 3 `CredentialService.load_encrypted()`. Adapters hold only a reveal callable, so decryption happens per request and never in the LLM package.
  - Startup does not require any LLM key. Calling the LLM with no key, or no configured model, raises `NoProviderConfigured`.
- **Trace** (`app/services/trace_recorder.py`, `trace_sanitize.py`, `app/schemas/trace.py`):
  - `TraceRecorder.record()` is the only write path. It sanitises, validates and appends one event per transaction, assigning gap-free per-run `seq` under a lock. `open()` continues an existing run's sequence.
  - Typed helpers: `agent_started`, `agent_completed`, `tool_call`, `llm_call` (built from `AttemptRecord`, metadata only, never prompts), `decision` (decision, handoff, replan or fallback), `validation` and `error`.
  - The redaction boundary removes values under credential-like keys (Authorization, Cookie, api_key, password, token, session, ciphertext, and so on). It also removes Groq/Google keys, Bearer values, Fernet tokens, Argon2 hashes, passwords in database URLs and opaque high-entropy tokens, while keeping UUIDs and hex paper IDs. Size limits: message 500, text 1000, raw excerpt 2000, 50 items, depth 6.
  - `GET /api/runs/{run_id}/events?after=&limit=` returns events to their owner only. Anyone else gets 404, and an unauthenticated request gets 401.
- **Migration `0002`:** creates `trace_events`, with (run_id, seq) unique, check constraints, a cascade-on-delete FK to `users`, and a self-FK on `parent_id`.
  - A trigger rejects UPDATE and direct DELETE. A delete is allowed only inside a foreign-key cascade, i.e. when a user account is deleted.
  - `run_id` deliberately has no FK until the `runs` table exists. Phase 7 adds one with a non-destructive `ALTER TABLE`.

## Phase 4 Validation (actually run, 2026-10-08)

- **Backend CI sequence, run locally:** `uv lock --check`, `uv sync --locked`, ruff check, ruff format --check and mypy (strict; app, tests, migrations) all pass. **pytest: 200 passed** (46 from Phase 3 plus 154 new) against real PostgreSQL 17, with no warnings.
- **Mutation checks:** I temporarily broke three things:
  - bypassing the trace sanitiser
  - removing key scrubbing from Groq errors
  - caching the decrypted key on the Gemini adapter

  The secret, size and retention tests failed for each. All three changes were reverted.
- **Alembic:**
  - upgrade 0001 → 0002, then `alembic check` (no drift)
  - trigger present
  - downgrade to 0001 removes the table and the function
  - base → head twice
- **Docker image:** builds, `alembic current` shows `0002 (head)` inside it, `/readyz` returns 200, and the events endpoint returns 401 without a session. `docker compose config` is valid.
- **gitleaks CLI 8.30.1:** git history and all 94 to-be-committed files are clean, and no real-key-shaped strings appear in tracked files.
- **Not run:** GitHub Actions (only runs after a push), the frontend (unchanged), and real Groq/Gemini calls, which no test makes.

## Phase 3: What Exists

**Backend (`backend/`, uv, Python 3.12)**
- **App:** `app/main.py` is the app factory (`uvicorn --factory app.main:create_app`). It refuses to start if `CREDENTIAL_ENCRYPTION_KEYS` is missing or invalid.
- **Config:** `app/config.py` reads `DATABASE_URL`, `CREDENTIAL_ENCRYPTION_KEYS`, `SESSION_*`, `FRONTEND_ORIGIN` and `ENVIRONMENT` from env or the root `.env`. Production refuses non-Secure cookies.
- **Database** (`app/db/`): async SQLAlchemy 2 + asyncpg. Small pool for Render Free and Neon Free. Repositories live in `app/db/repositories/`.
- **Schema** (Alembic `migrations/versions/0001_*`):
  - `users`: email unique and stored normalised (trimmed, lower-case), Argon2id hash.
  - `sessions`: SHA-256 of the opaque token, `expires_at`, `revoked_at`, FK cascade.
  - `user_provider_credentials`: Fernet ciphertext, last-4 hint, status `unverified`/`valid`/`invalid`, `validated_at`, timestamps. Unique on (user, provider), check constraints, FK cascade.
  - The table is named `user_provider_credentials`, as specified for Phase 3; the architecture doc calls it `api_credentials`.
  - Email uniqueness relies on normalisation rather than the `citext` extension.
- **Auth API** (`app/api/auth.py`, `app/services/auth.py`):
  - Endpoints: `register`, `login`, `logout`, `me` under `/api/auth`.
  - Sessions use a 256-bit random token that is sent only in the cookie `rp_session` (`HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` = TTL, `Secure` unless local dev). The expiry slides when less than half the TTL remains.
  - Login gives the same 401 for an unknown email and a wrong password, and runs a dummy hash so timing doesn't reveal which.
  - Each request runs in one transaction, committed before the response is sent.
- **Credentials API** (`app/api/credentials.py`, `app/services/credential_crypto.py`):
  - Endpoints: `GET /api/credentials`, `PUT /api/credentials/{groq|gemini}` (atomic upsert), `DELETE /api/credentials/{provider}`.
  - Keys are encrypted with MultiFernet, and key rotation is supported. Responses contain only metadata. Every query is scoped to the current user.
- **Security:**
  - The 422 handler never echoes submitted input such as passwords or keys.
  - An Origin check rejects cross-site state-changing requests (CSRF defence alongside `SameSite=Lax`).
  - `/readyz` checks PostgreSQL and returns 503 with no internal details. Health routes are served at the root (for the platform) and under `/api` (for the frontend proxy).
- **Dockerfile:** bundles the migrations and runs as a non-root user via the app factory.

**Frontend:** the rewrite now maps `/api/*` → `BACKEND_URL/api/*`. There is no UI work yet.

**CI** (`.github/workflows/ci.yml`): the backend job runs against a `postgres:17` service container, and mypy also checks `migrations`. The frontend job and the gitleaks CLI scan are unchanged.

## Development Setup

See [README.md](README.md). In short:

```bash
cp .env.example .env    # set the DB password and URLs, generate CREDENTIAL_ENCRYPTION_KEYS
docker compose up -d --wait && docker compose exec postgres createdb -U researchpilot researchpilot_test
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn --factory app.main:create_app --reload
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests migrations && uv run pytest
cd frontend && npm ci && npm run lint && npm run typecheck && npm run build
```

## Phase 3 Validation (actually run, 2026-10-08)

- **Backend:** ruff check, ruff format, mypy (strict, including migrations), `uv lock --check` and `uv sync --locked` all pass. **pytest: 46 passed** against real PostgreSQL 17, covering:
  - database config and migrations
  - registration, login and sessions
  - Argon2id storage
  - credential encryption and isolation between users
  - secrets kept out of logs, responses and exceptions
  - readiness
- **Mutation check:** disabling the input-redacting 422 handler made 3 leak tests fail. The handler was then restored.
- **Alembic:** upgrade from an empty DB, `alembic check` (no drift), downgrade to base, re-upgrade, and an idempotent second upgrade.
- **Live smoke test** (uvicorn + curl):
  - register → login → cookie set → `/me` → save a Groq key
  - the database row holds only a Fernet token, and the plaintext is absent
  - GET returns metadata only
  - a second user sees nothing and gets 404 on delete
  - after logout, the old token gets 401
  - `/readyz` returns 200 with the DB up and 503 with it stopped
  - the server logs contain no key
- **Next.js proxy:** the same auth flow works through `next start`, with the cookie on the frontend origin, and a cross-origin POST gets 403.
- **Docker image:** builds, `alembic current` works inside it, the container's `/readyz` returns 200, and it fails clearly without the encryption key.
- **Frontend:** lint, typecheck and build pass.
- **CI checks:** workflow YAML parses and `docker compose config` is valid.
- **gitleaks CLI 8.30.1:** git history is clean, and the 63 to-be-committed files scan clean.
- **Not yet run:** GitHub Actions. It will run on the next push.

## Known Issues / Deferred

- **Login rate limiting** (architecture §5, in-memory per IP and email) is not implemented yet; it is deferred to the Runs API hardening in Phase 7.
- **Expired sessions** are rejected but not deleted, so periodic cleanup is still to be added.
- **Credential validation** against Groq/Gemini (status `valid`/`invalid`) is not done yet. It needs a live list-models call on save, so it is deferred to Phase 6/7, where the runner can also mark keys `invalid` on an `auth_failed` error. Keys are stored as `unverified`, and the gateway skips keys marked `invalid`.
- **No default model IDs:** `GROQ_MODELS` and `GEMINI_MODELS` are empty by default because free-tier availability changes. Before Phase 6 runs, they must be set to models verified as free-tier with a real key.
- **Tool calling** (`generate_with_tools` in architecture §6) is not implemented. It arrives with the Search Agent in Phase 6 if that agent needs native function calling.
- **Semantic Scholar without a key** is often rate-limited (seen in the live smoke test). Searches still work through OpenAlex, but a free S2 key is recommended for demos.
- **SSRF DNS rebinding:** the DNS check and the connection are separate lookups, so a hostile DNS server could rebind between them. The fetcher blocks obvious SSRF but is not an egress firewall.
- **Literature rate limiter:** `build_literature_service()` creates a new Semantic Scholar limiter per service. Phase 6/7 should build one service per process so that pacing is shared.
- **No per-round or per-run search budget** (6 search requests per round, 15 papers per run) is enforced in the tools; those bounds belong to the Phase 6 orchestrator. The tools enforce only per-call limits.
- **Groq free-tier TPM:** Groq's tokens-per-minute limit (8K on gpt-oss) is the binding constraint for Document Analysis prompts (~4–5K tokens each, run two at a time). In the real run, 24 of 48 attempts were 429s, handled with `Retry-After` and fallbacks. Because rejected attempts count toward the 60-call budget, research stopped after iteration 2 (`budget_limit`). Recommendations: lower `GROQ_REQUESTS_PER_MINUTE`, prefer Gemini for analysis, or don't count 429-rejected attempts toward the budget (a deliberate design decision, left unchanged).
- **Execution is not durable:** runs live in the API process. A restart fails queued and running runs (`interrupted`), and there is no queue by design (free tier).
- **Free-tier model churn:** `gemini-2.5-*` disappeared for new users during development. Model IDs must be checked against the provider when deploying.
- **Trace `input_ref`** is still unused. `output_ref` links each `agent_completed` event to its first persisted output.
- **Trace agent names:** the trace uses the existing agent names (planner, search, analysis, synthesis, writer, orchestrator), with graph node names in messages and handoffs. The replanning node is recorded as `orchestrator`, so no trace migration was needed.
- **Quote grounding** uses normalised exact substring matching (case, whitespace, quote marks and dashes). It is stricter than the architecture's fuzzy ≥ 0.9, so slightly misquoted evidence is dropped and the paper gets one retry.
- **Search tool calling** uses the planned/refined query loop rather than native function calling, so `generate_with_tools` was not needed.
- **Budget:** the budget is checked before each LLM call and before each new iteration. A call already in progress can still add up to 6 provider requests (Phase 4 bound).
- **Registration** returns 409 for an existing email. This reveals the account exists, which can't be avoided without email verification, and the project has no email service (free-tier constraint).
- **Local ports:** on this development machine, 5432, 8000 and 3000 are used by other projects. Set `POSTGRES_PORT` and the URLs in `.env`, and pass `--port` to uvicorn and `-p` to Next.js.
- **Neon:** the asyncpg `ssl`/pooler settings for Neon are configured in Phase 9 (deployment).

## Notes From Earlier Phases

- Tailwind, TanStack Query and the other frontend libraries are deferred to Phase 8, which is the visual-design phase.
- `httpx2` (the Pydantic-maintained successor to httpx, which Starlette recommends) is the runtime HTTP client for the LLM adapters, the literature and PDF tools, and the test-client transport. Its built-in `MockTransport` replaces `respx` in tests.
- I used provider REST APIs instead of the `groq` / `google-genai` SDKs, which the architecture suggested. This means fewer dependencies, full control over headers and error text (so credentials can't leak), and simple mocking.
- Next.js evaluates `BACKEND_URL` at build time, so it must be set in Vercel's build environment.
- `npm audit` reports 0 production vulnerabilities. There are 5 high-severity advisories in dev-only ESLint tooling, left unchanged.

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

2. ~~Foundation~~ (complete)
3. ~~Database, auth and encrypted credentials~~ (complete)
4. ~~Agent contracts, LLM provider layer and trace recorder~~ (complete)
5. ~~Tools: OpenAlex, Semantic Scholar, dedupe, PDF~~ (complete)
6. ~~Agents, LangGraph orchestration and replanning~~ (complete)
7. ~~Runs API, end-to-end tests and first real trace~~ (complete)
8. Frontend
9. Deployment
10. Final documentation and demo
