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

**Phase 4 complete: agent contracts, LLM provider layer and trace recorder.** The five agents, LangGraph orchestration, literature tools and research runs do not exist yet. Design: [docs/PHASE1_ARCHITECTURE.md](docs/PHASE1_ARCHITECTURE.md).

**Next:** Phase 5, Tools (OpenAlex, Semantic Scholar, dedupe, PDF).

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
- **Per-run budget** (60 calls / 200k tokens) and provider fallback across a run are orchestration concerns for Phase 6. The gateway already exposes ordered `candidates()` and per-call `AttemptRecord`s for them.
- **Registration** returns 409 for an existing email. This reveals the account exists, which can't be avoided without email verification, and the project has no email service (free-tier constraint).
- **Local ports:** on this development machine, 5432, 8000 and 3000 are used by other projects. Set `POSTGRES_PORT` and the URLs in `.env`, and pass `--port` to uvicorn and `-p` to Next.js.
- **Neon:** the asyncpg `ssl`/pooler settings for Neon are configured in Phase 9 (deployment).

## Notes From Earlier Phases

- Tailwind, TanStack Query and the other frontend libraries are deferred to Phase 8, which is the visual-design phase.
- `httpx2` (the Pydantic-maintained successor to httpx, which Starlette recommends) is the runtime HTTP client for the LLM adapters and the test-client transport. Its built-in `MockTransport` replaces `respx` in tests.
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
5. Tools: OpenAlex, Semantic Scholar, dedupe, PDF
6. Agents, LangGraph orchestration and replanning
7. Runs API, end-to-end tests and first real trace
8. Frontend
9. Deployment
10. Final documentation and demo
