# ResearchPilot

**Multi-Agent AI Research & Literature Review System**: Team Decepticons.

ResearchPilot turns a research question into a cited literature review. Five agents (Research Planner, Literature Search, Document Analysis, Evidence Synthesis, Review Writer) coordinate through a LangGraph state graph. The Evidence Synthesis Agent can send the run back for more research when the evidence is insufficient or contradictory, and the loop is bounded. Each run produces a real execution trace of the agent handoffs and decisions.

> Status: **Phase 3 (database, auth, encrypted credentials)**. The backend has PostgreSQL with Alembic migrations, email/password auth with database sessions, and encrypted storage for each user's Groq/Gemini keys. There are no agents yet. See [PROJECT_STATE.md](PROJECT_STATE.md) and [docs/PHASE1_ARCHITECTURE.md](docs/PHASE1_ARCHITECTURE.md).

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

## API (Phase 3)

| Endpoint | Purpose |
|---|---|
| `GET /healthz`, `GET /readyz` (also under `/api`) | Liveness check; readiness check, which includes a PostgreSQL query |
| `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | Email/password auth with an httpOnly session cookie |
| `GET /api/credentials`, `PUT /api/credentials/{groq,gemini}`, `DELETE /api/credentials/{provider}` | Encrypted provider API keys. Only metadata is returned, never the key |

## Checks

These are the same commands CI runs. Backend tests need `TEST_DATABASE_URL` (from `.env`) pointing at a database whose name ends in `_test`. The tests apply the migrations themselves and truncate the tables.

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests migrations && uv run pytest
cd frontend && npm run lint && npm run typecheck && npm run build
```
