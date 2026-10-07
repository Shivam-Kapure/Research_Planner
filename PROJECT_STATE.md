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

**Phase 3 complete: database, authentication and encrypted user credentials.** There are no agents, LLM calls, literature tools, runs or traces yet. Design: [docs/PHASE1_ARCHITECTURE.md](docs/PHASE1_ARCHITECTURE.md).

**Next:** Phase 4, Agent contracts, LLM provider layer and trace recorder.

## What Exists

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
- **Credential validation** against Groq/Gemini (status `valid`/`invalid`) arrives with the LLM provider layer in Phase 4. Until then keys are stored as `unverified`.
- **Registration** returns 409 for an existing email. This reveals the account exists, which can't be avoided without email verification, and the project has no email service (free-tier constraint).
- **Local ports:** on this development machine, 5432, 8000 and 3000 are used by other projects. Set `POSTGRES_PORT` and the URLs in `.env`, and pass `--port` to uvicorn and `-p` to Next.js.
- **Neon:** the asyncpg `ssl`/pooler settings for Neon are configured in Phase 9 (deployment).

## Notes From Earlier Phases

- Tailwind, TanStack Query and the other frontend libraries are deferred to Phase 8, which is the visual-design phase.
- Backend tests use `httpx2` as the test-client transport, as Starlette recommends. Which HTTP client the runtime uses for external APIs will be confirmed in Phase 5.
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
4. Agent contracts, LLM provider layer and trace recorder
5. Tools: OpenAlex, Semantic Scholar, dedupe, PDF
6. Agents, LangGraph orchestration and replanning
7. Runs API, end-to-end tests and first real trace
8. Frontend
9. Deployment
10. Final documentation and demo
