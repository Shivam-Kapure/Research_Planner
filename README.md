# ResearchPilot

**Multi-Agent AI Research & Literature Review System**: Team Decepticons (CA3).

ResearchPilot turns a research question into a cited literature review. Five specialised agents plan the research, search the academic literature, analyse the papers, judge the evidence and write the review. When the evidence is insufficient or contradictory, the system **changes course on its own** by revising the search or the research scope, within fixed limits. Every step is recorded in a real execution trace that the UI shows live.

**Live:** https://researchpilot-rho.vercel.app. The backend is https://researchpilot-api-78oo.onrender.com. Status: implemented, tested, deployed, documented (see [PROJECT_STATE.md](PROJECT_STATE.md)).

| Document | Contents |
|---|---|
| [docs/FINAL_ARCHITECTURE.md](docs/FINAL_ARCHITECTURE.md) | As-built architecture: diagram, agents, contracts, replanning, security, deployment, limits |
| [docs/CA3_EVIDENCE_INDEX.md](docs/CA3_EVIDENCE_INDEX.md) | Each CA3 requirement mapped to evidence |
| [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md) and [docs/DEMO_TALKING_POINTS.md](docs/DEMO_TALKING_POINTS.md) | Demo flow and answers to evaluator questions |
| [docs/PHASE6_MULTI_AGENT.md](docs/PHASE6_MULTI_AGENT.md) | Agents, graph, validation, trace model |
| [docs/PHASE7_RUNS_API.md](docs/PHASE7_RUNS_API.md) | Runs API, lifecycle, first real runs |
| [docs/PHASE1_ARCHITECTURE.md](docs/PHASE1_ARCHITECTURE.md) | Original design (deviations listed in FINAL_ARCHITECTURE §20) |
| [docs/traces/](docs/traces/) | Unedited exports of real runs |

## Features

- A research workspace: ask a question, set iterations (1–3) and a year range.
- A **live agent timeline** built from the trace: steps, tool and model calls, verdicts, replanning, limits and errors.
- The final review as an article, with `[Pn]` citations linked to references built from metadata, stated limitations and an evidence status.
- Evidence and outputs inspection: coverage per sub-question, contradictions, each paper's analysis with verbatim quotes, and the raw contracts.
- Run history, cancellation, and a waking screen for free-tier cold starts.
- Users bring their own free-tier Groq or Gemini keys, which are stored encrypted on the server.

## Architecture

```
Browser → Vercel (Next.js) ──/api proxy──→ Render (FastAPI + LangGraph, Docker) → Neon PostgreSQL
                                                  │
              OpenAlex · Semantic Scholar · open-access PDFs · Groq · Gemini
```

The full Mermaid diagram is in [FINAL_ARCHITECTURE §2](docs/FINAL_ARCHITECTURE.md#2-architecture-diagram).

## Agents and adaptive replanning

| Agent | Does | Produces |
|---|---|---|
| Research Planner | Sub-questions, priorities, keywords, strategy, criteria | `ResearchPlan` |
| Literature Search | Queries OpenAlex and Semantic Scholar, deduplicates, ranks, screens | `SearchResults` |
| Document Analysis | Reads open-access full text (or the abstract) and extracts claims with verbatim, grounded quotes | `DocumentAnalysis` |
| Evidence Synthesis | Coverage, themes and contradictions → `sufficient` / `insufficient` / `contradictory`, checked by deterministic rules | `SynthesisDecision`, `ReplanningRequest` |
| Review Writer | Structured, cited review with limitations | `FinalReview` |

```
Planner → Search → Analysis → Synthesis ─┬─ sufficient ────────────────────────→ Writer
                                         ├─ insufficient  → search revision → Search
                                         ├─ contradictory → scope revision  → Planner (plan v+1)
                                         └─ limit reached (3 iterations / 60 LLM calls / 200k tokens) → Writer
```

Agents communicate only through these typed contracts, held in LangGraph state. Real runs that replanned:
- `34908068`: search revision, then the budget limit.
- `d29bb92b`: search revision, then sufficient.
- `9403b69c` (production): two search revisions, then the iteration limit.

## Tech stack

| Layer | Technology | Hosting (free tiers only) |
|---|---|---|
| Backend | Python 3.12, FastAPI, LangGraph, Pydantic v2, SQLAlchemy 2 (async) + asyncpg, Alembic, httpx2, pypdf, uv | Render Free (Docker) |
| Frontend | Next.js 16 (App Router), React 19, TypeScript (strict), plain CSS | Vercel Hobby |
| Database | PostgreSQL 17 (Docker Compose locally) | Neon Free |
| LLMs | Groq and/or Gemini via their REST APIs, using each user's free-tier key | — |
| Literature | OpenAlex, Semantic Scholar, open-access PDFs | — |

## Local setup

You need Python 3.12 and [uv](https://docs.astral.sh/uv/), Node.js 24 and npm, and Docker Desktop.

```bash
cp .env.example .env
```

Then edit `.env`:
1. Set `POSTGRES_PASSWORD` and use the same password in `DATABASE_URL` and `TEST_DATABASE_URL`. If a port is taken, change `POSTGRES_PORT` and both URLs.
2. Set `CREDENTIAL_ENCRYPTION_KEYS` to a key generated with:
   ```bash
   cd backend && uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. Set `SESSION_COOKIE_SECURE=false` (needed for local plain http only).
4. Set `GROQ_MODELS` / `GEMINI_MODELS`. The values used in production are listed under Production deployment.

From the repository root:

```bash
docker compose up -d --wait
docker compose exec postgres createdb -U researchpilot researchpilot_test   # once, for the tests
```

Terminal 1, the backend on http://localhost:8000:

```bash
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn --factory app.main:create_app --reload
```

Terminal 2, the frontend on http://localhost:3000:

```bash
cd frontend && npm ci && npm run dev
```

- **Ports:** the frontend proxies `/api/*` to `BACKEND_URL` (default `http://localhost:8000`; override it in `frontend/.env.local`). If you use other ports, set `FRONTEND_ORIGIN` in `.env` to the exact address you browse.
- **Stopping:** `docker compose stop` stops Postgres. `docker compose down -v` also **deletes** the local database.

## Production deployment (free tiers)

| Part | Service | Configuration |
|---|---|---|
| Frontend | Vercel Hobby, root directory `frontend` | `BACKEND_URL=https://<render-service>.onrender.com` (read at build time, so redeploy after changing it) |
| Backend | Render Free web service, Docker, root `backend`, health check `/healthz` | `DATABASE_URL`, `CREDENTIAL_ENCRYPTION_KEYS` (a production-only key), `ENVIRONMENT=production`, `SESSION_COOKIE_SECURE=true`, `FRONTEND_ORIGIN=https://<vercel-domain>`, `GROQ_MODELS=openai/gpt-oss-20b,openai/gpt-oss-120b`, `GEMINI_MODELS=gemini-3.5-flash-lite,gemini-3.5-flash`, `GROQ_REASONING_EFFORT=low`, `GEMINI_THINKING_LEVEL=low` |
| Database | Neon Free PostgreSQL 17 | Use the direct endpoint, with the URL ending in `?ssl=require` (asyncpg does not accept Neon's `sslmode`/`channel_binding` parameters) |

Secrets are entered only in the dashboards, never in the repository. No provider key is configured on Render or Vercel: users add their own in Settings.

Run migrations from your machine (Render Free has no pre-deploy step). This PowerShell command keeps the URL off the screen and out of the history:

```powershell
$s = Read-Host "Neon DATABASE_URL" -AsSecureString; $env:DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)); cd backend; uv run alembic upgrade head; uv run alembic current; Remove-Item Env:DATABASE_URL; cd ..
```

Health: `/healthz` (liveness) and `/readyz` (database check), also under `/api`.

## API overview

| Endpoint | Purpose |
|---|---|
| `POST /api/auth/register`, `login`, `logout`, `GET /api/auth/me` | Email/password auth with an httpOnly session cookie |
| `GET /api/credentials`, `PUT /api/credentials/{groq,gemini}`, `DELETE /api/credentials/{provider}` | Encrypted provider keys; only metadata is ever returned |
| `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{id}`, `POST /api/runs/{id}/cancel` | Create (202, runs in the background), list, poll and cancel runs |
| `GET /api/runs/{id}/events?after=&limit=`, `/outputs`, `/result` | Append-only trace (polling cursor), agent outputs, final review |

See [docs/PHASE7_RUNS_API.md](docs/PHASE7_RUNS_API.md).

## LLM provider setup

Each user creates a free key at the [GroqCloud console](https://console.groq.com/keys) (keys start with `gsk_`) and/or [Google AI Studio](https://aistudio.google.com/apikey), then adds it under **Settings**. Keys are checked with the provider on save, encrypted, and never shown again. Model IDs and reasoning budgets are server configuration (see above), because free-tier model availability changes.

## Security

- **Accounts and sessions:**
  - Passwords are hashed with Argon2id.
  - Sessions use opaque tokens (only their hash is stored) in an `HttpOnly; Secure; SameSite=Lax` cookie.
  - State-changing requests must come from `FRONTEND_ORIGIN`.
- **Provider keys:**
  - Encrypted with MultiFernet and decrypted per request.
  - Never in graph state, traces, logs, responses or the frontend.
- **Traces and errors:**
  - The trace sanitiser redacts credentials.
  - 422 responses never echo input.
- **Data and network:**
  - Every query is scoped to its owner; another user's run returns 404.
  - The SSRF-safe PDF fetcher checks every redirect hop.
  - HTTPS with HSTS in production.
- **Repository:** gitleaks scans the git history in CI.

Details: [FINAL_ARCHITECTURE §16](docs/FINAL_ARCHITECTURE.md#16-security-boundaries).

## Testing

```bash
cd backend && uv lock --check && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests migrations && uv run pytest
cd frontend && npm run lint && npm run typecheck && npm run build && npm test
```

- **Backend:** 388 pytest tests against real PostgreSQL. They cover:
  - contracts, the LLM layer (mocked HTTP), tools (mock transports, PDF fixtures, an SSRF matrix)
  - each agent with a scripted LLM, full-graph adaptive paths, the Runs API end to end
  - auth, credentials, migrations, and secret leakage
- **Frontend:** 40 `node:test` tests: timeline derivation on a real trace, polling, API errors, Markdown safety, components, validation.
- **CI:** GitHub Actions runs all of the above plus gitleaks. No test calls a real LLM or literature API.
- **Not covered:** there is no Playwright end-to-end test, and the mutation checks were partial. See [PROJECT_STATE.md](PROJECT_STATE.md).

## Free-tier constraints and known limitations

- **Render Free sleeps after about 15 minutes idle.** The first request takes 30–60 s, and the UI shows a waking screen.
- **Runs execute in the API process** (no queue, by design). A restart marks running runs `failed: interrupted`.
- **Groq's free tokens-per-minute limit** causes 429s. They're retried and fall back to other models, but they count toward the 60-call budget.
- **Free models get retired.** Model IDs are configuration and need occasional updates.
- **Semantic Scholar's public pool** is often rate-limited; search continues on OpenAlex alone.
- **Deduplication matches exact DOIs**, so different versions of one paper can appear separately.
- **The UI polls** rather than streaming.
- **Contradictory → scope revision** has only been exercised by automated tests, not by a real run.

## Demo

See [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md). Screenshots still to capture are listed in [docs/SCREENSHOT_CHECKLIST.md](docs/SCREENSHOT_CHECKLIST.md).
