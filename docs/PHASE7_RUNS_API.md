# Phase 7: Runs API, Persistence and the First Real Run

The Runs API turns the Phase 6 graph into a usable backend. An authenticated user `POST`s a research question. The backend creates a `runs` row and runs the **same Phase 6 `run_research()`** in an in-process asyncio task. That task uses the user's encrypted free-tier Groq/Gemini keys and persists agent outputs and the trace as it goes. The client polls for status and reads the result.

## Endpoints

All endpoints require the Phase 3 session cookie. Another user's run always returns **404**, never 403, and unauthenticated requests get **401**. FastAPI's OpenAPI document (`/openapi.json`) is generated from the Pydantic models in `app/schemas/api/runs.py`.

| Method & path | Purpose | Responses |
|---|---|---|
| `POST /api/runs` | Body: `ResearchRequest` (`question`, `max_iterations` 1–3, `year_from`, `year_to`). Creates a run and starts it in the background | **202** `RunDetail`; 409 if the user already has a queued or running run; 422 for an invalid request (input never echoed) |
| `GET /api/runs?limit=20&offset=0` | The user's runs, newest first, metadata only | 200 `RunPage {items, total, limit, offset}` (limit ≤ 50) |
| `GET /api/runs/{id}` | Status for polling | 200 `RunDetail` |
| `GET /api/runs/{id}/events?after=&limit=` | Append-only trace in `seq` order; `after` is the cursor | 200 `TraceEvent[]` |
| `GET /api/runs/{id}/outputs?agent=&iteration=` | Persisted agent outputs in production order | 200 `AgentOutput[]` |
| `GET /api/runs/{id}/result` | Outcome of a finished run | 200 `RunResult`; **409** while queued or running |
| `POST /api/runs/{id}/cancel` | Cancel a queued or running run | 202; 409 if not active |

`RunDetail` contains:
- `id`, `question`, `status`, `iteration`, `stop_reason`
- `created_at`, `started_at`, `updated_at`, `completed_at`
- `request`
- `error {code, message, node}`
- `progress {iteration, max_iterations, llm_calls, max_llm_calls, tokens_used, max_tokens}`

`RunResult` is `{run_id, status, stop_reason, review: FinalReview | null, synthesis: SynthesisDecision | null, error}`.

```json
// POST /api/runs  {"question": "What is the effect of regular aerobic exercise on blood pressure in adults with hypertension?", "year_from": 2015}
// → 202
{"id": "…", "status": "queued", "iteration": 0, "stop_reason": null, "error": null,
 "progress": {"iteration": 0, "max_iterations": 3, "llm_calls": 0, "max_llm_calls": 60, "tokens_used": 0, "max_tokens": 200000}, …}
```

## Lifecycle and statuses

`queued` → `running` → one of:

| Status | Meaning |
|---|---|
| `completed` | The evidence was judged sufficient and the review was written |
| `completed_with_limitations` | A review was written after an iteration or budget stop; `stop_reason` and the review's `limitations` explain why |
| `partial` | Synthesis exists but a later step failed (e.g. the Writer); the result carries the last synthesis |
| `failed` | A fatal error occurred (no provider or model configured, a rejected key, literature unavailable, planner or synthesis failure, or a restart); see `error` |
| `cancelled` | The user cancelled the run |

## Execution and its limits

- **In-process asyncio, no queue** (architecture §2, Render Free). An `asyncio.Semaphore` limits concurrent runs (`MAX_CONCURRENT_RUNS`, default 1); extra runs stay `queued`. Each user can have one active run.
- **Not durable.** Queued and running tasks live in the API process. After a restart, the startup sweep marks them `failed` with error `interrupted`.
- **Budgets:** the Phase 6 `ResearchLimits`/`RunBudget` apply per run and are never reset by replanning:
  - 3 iterations
  - 15 papers
  - 60 LLM calls
  - 200k tokens
  - a 20-minute timeout
  - the per-iteration search and document limits
- **Persistence as agents finish.** Each node writes its Phase 4 contracts to `agent_outputs` as soon as it completes (plan, search request/results, each analysis, the decision, the replanning request, the review). `trace_events.output_ref` points to them, and `runs` progress (iteration, LLM calls, tokens) is updated at every node. A failed run keeps everything produced before the failure.
- **Keys:** keys are checked when saved (`PUT /api/credentials/{provider}` makes one model-list call → `valid`/`invalid`/`unverified`). If a provider rejects a key mid-run, the key is marked `invalid` and the run fails or falls back. Startup never needs an LLM key.

## Data model (migration `0003`)

- `runs`: owner, question, `request` (JSONB), status (check constraint), iteration, stop reason, safe `error` JSONB, LLM calls/tokens, and timestamps; indexed on (`user_id`, `created_at`).
- `agent_outputs`: run (cascade), agent, iteration, `schema_name`/`schema_version` and the contract JSON payload. Prompts, keys, PDFs and full text are never stored; evidence quotes are limited to 600 characters.
- `trace_events.run_id → runs.id` (ON DELETE CASCADE) was added **NOT VALID**: trace rows from before Phase 7 are kept and every new row is checked. The append-only trigger still blocks UPDATE and direct DELETE; cascades from a run or user deletion are allowed.

## Model configuration (free tiers)

Model IDs are configuration, set in the untracked root `.env`. Keys are never set there; they go only through the credentials API.

| Setting | Live-run value | Why |
|---|---|---|
| `GEMINI_MODELS` | `gemini-3.5-flash-lite,gemini-3.5-flash` | `gemini-2.5-*` returned HTTP 404 "no longer available to new users" |
| `GEMINI_THINKING_LEVEL` | `low` | Gemini 3.x rejects `thinkingBudget: 0` |
| `GROQ_MODELS` | `openai/gpt-oss-20b,openai/gpt-oss-120b` | Free plan: 30 RPM, 8K TPM, 200K tokens/day |
| `GROQ_REASONING_EFFORT` | `low` | At the default effort the reasoning tokens used up the output budget and the JSON was empty |

Get free keys from Google AI Studio (Gemini) and the GroqCloud console. Enter them after login with `PUT /api/credentials/{groq|gemini}`; they're checked, encrypted and never returned.

## First real runs (2026-10-07 UTC, local development stack)

Question: *"What is the effect of regular aerobic exercise on blood pressure in adults with hypertension?"* (`year_from` 2015). Every attempt is kept in the database as it happened:

| Run | Outcome | What it revealed → fix |
|---|---|---|
| `accaccc5` | `failed` at the Planner (12 events) | gpt-oss at default reasoning effort returned empty JSON (Groq `json_validate_failed`); the fallback to `gemini-2.5-flash-lite` returned 404 (model retired for new users) → added `GROQ_REASONING_EFFORT`, `GEMINI_THINKING_LEVEL`, and switched to Gemini 3.5 models |
| `769ca6b8` | `partial` (122 events): 2 iterations, synthesis `sufficient`, Writer rejected | The Writer's retry message described the wrong problem; quote grounding missed U+2011 hyphens → accurate retry feedback and wider Unicode folding |
| `531f100b` | `partial` (127 events) | `gemini-3.5-flash-lite` ignored the citation instruction in the prompt; a replay on the persisted outputs confirmed it → the citation rule was added to the Writer's output-schema description, and it then cited every body section |
| **`34908068`** | **`completed_with_limitations`** (125 events, 48 LLM calls, 80k tokens) | See below |

**Run `34908068`**, exported unedited to `docs/traces/2026-10-07_run-34908068.json`:
- Path: `planner → search → analysis → synthesis(insufficient) → replanning(search_revision) → search → analysis → synthesis(insufficient) → routing: limit_reached (budget_limit) → writer`.
- 12 literature searches. The iteration-2 queries targeted the gaps synthesis named, for example "meta analysis aerobic exercise diastolic blood pressure…".
- 12 document retrievals: 4 full text, 8 abstract-only.
- 48 LLM calls across `gpt-oss-20b`, `gpt-oss-120b` (3 traced fallbacks) and `gemini-3.5-flash-lite`.
- A 4-section review with 7 metadata-built references and explicit limitations.
- **Secret scan:** both provider keys, the session cookie, the password hash and the encryption key were absent from `runs`, `agent_outputs`, `trace_events`, every API response and the server logs; no `Bearer`/`x-goog-api-key` text anywhere.

## Frontend integration (Phase 8)

- **Polling:** after `POST`, poll `GET /api/runs/{id}` (about every 2 s) and `GET /events?after=<last seq>` for a live agent timeline. Stop when `status` is terminal, then fetch `/result` and `/outputs`.
- **Rendering:**
  - `FinalReview` is the review: Markdown sections with `[@Pn]` keys that map to `references`.
  - `limitations` and `evidence_status` must be shown prominently.
  - `outputs` provide the plan, papers and evidence for drill-down.
- **Visual direction:** editorial and story-led, not a dashboard. Inspiration from the restraint, typography, whitespace and section rhythm of lujoliving.com (no content, branding or assets copied).
