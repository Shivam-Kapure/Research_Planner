# ResearchPilot

**Multi-Agent AI Research & Literature Review System**: Team Decepticons.

ResearchPilot turns a research question into a cited literature review. Five agents (Research Planner, Literature Search, Document Analysis, Evidence Synthesis, Review Writer) coordinate through a LangGraph state graph. The Evidence Synthesis Agent can send the run back for more research when the evidence is insufficient or contradictory, and the loop is bounded. Each run produces a real execution trace of the agent handoffs and decisions.

> Status: **Phase 6 (five agents + LangGraph adaptive loop)**. The backend has auth, encrypted user keys, versioned inter-agent contracts, a Groq/Gemini provider layer, an append-only execution trace, literature and open-access PDF tools, and the five-agent LangGraph workflow with deterministic sufficiency validation and bounded replanning. There is no Runs API or frontend yet. See [PROJECT_STATE.md](PROJECT_STATE.md) and [docs/PHASE1_ARCHITECTURE.md](docs/PHASE1_ARCHITECTURE.md).

## Stack

| Layer | Technology | Hosting (free tiers only) |
|---|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async) + asyncpg, Alembic, uv | Render Free |
| Frontend | Next.js (App Router), TypeScript | Vercel Hobby |
| Database | PostgreSQL 17 (Docker locally) | Neon Free |
| LLMs | Groq and/or Gemini, using free-tier keys supplied by each user | — |

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js 24 and npm
- Docker Desktop, or a native PostgreSQL 17 install

## Setup

```bash
cp .env.example .env
```

Then edit `.env`:

1. Set `POSTGRES_PASSWORD`, and use the same password in `DATABASE_URL` and `TEST_DATABASE_URL`. If port 5432 is already in use, change `POSTGRES_PORT` and the port in both URLs.
2. Generate an encryption key and paste it into `CREDENTIAL_ENCRYPTION_KEYS`:
   ```bash
   cd backend && uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   If you lose this key, stored provider keys can no longer be decrypted.
3. Keep `SESSION_COOKIE_SECURE=false` only for local plain-http development. It must be `true` in production.

Optionally, create `frontend/.env.local` containing `BACKEND_URL=http://localhost:8000`, which is the default.

Real API keys, passwords, database URLs and secrets must **never** be committed. Only `.env.example` (placeholders) is tracked.

## Run locally

```bash
# Local PostgreSQL, plus the disposable test database (create it once)
docker compose up -d --wait
docker compose exec postgres createdb -U researchpilot researchpilot_test

# Backend: apply migrations, then serve on http://localhost:8000 (/healthz, /readyz, /api/...)
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn --factory app.main:create_app --reload

# Frontend: http://localhost:3000 (proxies /api/* to BACKEND_URL/api/*)
cd frontend
npm ci
npm run dev
```

`BACKEND_URL` is read when Next.js builds its rewrites, so on Vercel it must be set before the build.

Remove the local database and its data with `docker compose down -v`.

## API

| Endpoint | Purpose |
|---|---|
| `GET /healthz`, `GET /readyz` (also under `/api`) | Liveness check; readiness check, which includes a PostgreSQL query |
| `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | Email/password auth with an httpOnly session cookie |
| `GET /api/credentials`, `PUT /api/credentials/{groq,gemini}`, `DELETE /api/credentials/{provider}` | Encrypted provider API keys. Only metadata is returned, never the key |
| `GET /api/runs/{run_id}/events?after=&limit=` | The owner's execution-trace events in sequence order (polling cursor) |

## LLM providers

- **Providers:** Groq and Gemini, called through their REST APIs (`app/llm/groq.py`, `app/llm/gemini.py`) behind one provider-neutral interface, `LLMGateway`. Free-tier keys are enough: the app never asks users to enable billing. It works with Groq only, Gemini only, or both.
- **Keys:** each user adds their own key with `PUT /api/credentials/{provider}`, and it is stored encrypted. The gateway decrypts it per request through the Phase 3 credential service. Keys never appear in environment variables, contracts, traces, logs or responses.
- **Models:** model IDs are configuration (`GROQ_MODELS`, `GEMINI_MODELS`, comma-separated candidates in order of preference). Nothing is hard-coded. List only models the provider currently offers on its free tier.
- **Rate limits:** `GROQ_REQUESTS_PER_MINUTE` / `GEMINI_REQUESTS_PER_MINUTE` pace calls to stay within free-tier limits. `LLM_REQUEST_TIMEOUT_S` sets the request timeout, and `GEMINI_THINKING_BUDGET` is optional.
- **Structured output:** the gateway requests JSON, validates it against a Pydantic contract, and allows at most one repair round. Transient failures are retried at most twice, so one call never makes more than 6 provider requests.

Real API keys must never be committed. Automated tests never call Groq or Gemini; they use mocked HTTP transports and scripted providers.

## Literature and document tools (`backend/app/tools/`)

These are deterministic tools that the agents call: they make no LLM calls and no research decisions.

- **Search:** `LiteratureSearchService.search(SearchQuery(...))` queries **OpenAlex** (primary) and **Semantic Scholar** (secondary) in parallel. It normalises both into one `Paper` model, then deduplicates and caps the results.
  - Per call: ≤ 25 results per source, ≤ 3 pages, ≤ 40 combined.
  - If one source fails, the result is marked degraded. Only if both fail does it raise `LiteratureUnavailable`.
  - Both APIs are free. `OPENALEX_EMAIL`, `OPENALEX_API_KEY` and `SEMANTIC_SCHOLAR_API_KEY` are **optional free** credentials. Without a Semantic Scholar key, the shared public pool is often rate-limited (429). Keys never appear in URLs that get logged (log records drop query strings) or in errors.
- **Dedupe and ranking:**
  - `deduplicate()` matches by exact DOI, then provider IDs, then title + year + first-author surname (no fuzzy matching). Merged papers keep the provenance of every source.
  - `rank_papers()` gives a transparent, deterministic score with per-signal breakdown: provider rank, citations, recency, open access and completeness.
  - `filter_papers()` filters by year, abstract and open access.
- **Documents:** `retrieve_document(paper, fetcher=SafePdfFetcher(client))` returns a `DocumentResult` with mode `full_text`, `abstract_only` or `unavailable`, plus a `failure_reason`.
  - Only explicit **open-access PDF URLs** reported by the providers are fetched. Landing pages are never scraped, and paywalls or logins are never bypassed.
  - Each download is validated:
    - only http/https on the default ports, with no credentials in the URL
    - public IPs only, re-checked on every redirect (≤ 3)
    - no https → http downgrade
    - a PDF content type and `%PDF-` signature
    - **≤ 15 MB**, streamed, with a 30 s overall timeout
  - PDFs are held in memory and never written to disk.
  - pypdf extracts text page by page (≤ 40 pages). Scanned or text-less PDFs fall back to the abstract (there is no OCR).
  - `DocumentResult.excerpt()` returns page-numbered text within about 16k characters (~4k tokens) and stops at the reference list.

Tool tests use `httpx2.MockTransport` and local PDF fixtures (`backend/tests/fixtures/pdf/`), so they need no network or keys.

## Agents and orchestration (`backend/app/agents/`, `backend/app/orchestration/`)

Five agents — Planner, Literature Search, Document Analysis, Evidence Synthesis and Review Writer — run as nodes of a LangGraph `StateGraph`:
- Evidence Synthesis returns `sufficient`, `insufficient` or `contradictory`. Deterministic rules can override that verdict, and an override is traced.
- When more research is needed, the graph loops back: a *search revision* goes to Search, and a *scope revision* goes to the Planner.
- The loop is limited to 3 iterations, after which the Writer reports the limitations.
- `run_research(runtime, request)` runs the graph and records a full trace.

See [docs/PHASE6_MULTI_AGENT.md](docs/PHASE6_MULTI_AGENT.md). The graph tests use a scripted LLM, so they need no API keys or network:

```bash
cd backend && uv run pytest tests/test_research_graph.py tests/test_agents.py tests/test_research_secrets.py
```

## Checks

These are the same commands CI runs. Backend tests need `TEST_DATABASE_URL` (from `.env`) pointing at a database whose name ends in `_test`. The tests apply the migrations themselves and truncate the tables. They cover the contracts, the LLM layer, the trace recorder and its redaction, the literature and PDF tools, and auth and credentials. None of them need network access to an LLM or literature provider.

To run only the tool tests:

```bash
cd backend && uv run pytest tests/test_tools_literature_clients.py tests/test_tools_dedupe_ranking.py tests/test_tools_literature_search.py tests/test_tools_documents.py
```

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests migrations && uv run pytest
cd frontend && npm run lint && npm run typecheck && npm run build
```
