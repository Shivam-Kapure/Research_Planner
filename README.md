# ResearchPilot

**Multi-Agent AI Research & Literature Review System**: Team Decepticons.

ResearchPilot turns a research question into a cited literature review. Five agents (Research Planner, Literature Search, Document Analysis, Evidence Synthesis, Review Writer) coordinate through a LangGraph state graph. The Evidence Synthesis Agent can send the run back for more research when the evidence is insufficient or contradictory, and the loop is bounded. Each run produces a real execution trace of the agent handoffs and decisions.

> Status: **Phase 2 (foundation)**. Only the backend health endpoints and a frontend shell exist. See [PROJECT_STATE.md](PROJECT_STATE.md) and [docs/PHASE1_ARCHITECTURE.md](docs/PHASE1_ARCHITECTURE.md).

## Stack

| Layer | Technology | Hosting (free tiers only) |
|---|---|---|
| Backend | Python 3.12, FastAPI, uv | Render Free |
| Frontend | Next.js (App Router), TypeScript | Vercel Hobby |
| Database | PostgreSQL 17 (Docker locally) | Neon Free |
| LLMs | Groq and/or Gemini, using free-tier keys supplied by each user | — |

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js 24 and npm
- Docker Desktop, or a native PostgreSQL 17 install

## Setup

```bash
cp .env.example .env    # backend + local Postgres settings; replace the placeholders
```

Optionally, create `frontend/.env.local` containing `BACKEND_URL=http://localhost:8000`, which is the default.

Real API keys, passwords, database URLs and secrets must **never** be committed. Only `.env.example` (placeholders) is tracked.

## Run locally

```bash
# Local PostgreSQL (port configurable via POSTGRES_PORT in .env)
docker compose up -d --wait

# Backend: http://localhost:8000/healthz and /readyz
cd backend
uv sync
uv run uvicorn app.main:app --reload

# Frontend: http://localhost:3000 (proxies /api/* to BACKEND_URL, default http://localhost:8000)
cd frontend
npm ci
npm run dev
```

`BACKEND_URL` is read when Next.js builds its rewrites, so on Vercel it must be set before the build.

## Checks

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests && uv run pytest
cd frontend && npm run lint && npm run typecheck && npm run build
```
