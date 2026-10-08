# Demo Talking Points

Short answers, each based on the implementation. File references are relative to `backend/app/` unless stated.

**Why is this multi-agent?**
Five agents (`agents/`), each with its own role, prompt, LLM output schema and typed output contract. No agent does another's job: Search never analyses, Analysis never synthesises, and the Writer can't change the verdict.

**Why isn't this just one LLM with tools?**
- **Control flow is a graph.** The decisions are made by Evidence Synthesis and checked by deterministic code, which routes the run to different agents.
- **Each step is validated separately.** Grounding, coverage and citations are enforced by code between steps.
- **Partial work survives.** A failure in one agent leaves the others' outputs in place.

**How do agents communicate?**
Through versioned Pydantic contracts in LangGraph state: `ResearchPlan` → `SearchResults` → `DocumentAnalysis` → `SynthesisDecision` / `ReplanningRequest` → `FinalReview`. They are immutable and reject unknown fields. There is no free-form agent-to-agent chat.

**How does replanning happen, and what causes it?**
- Synthesis judges the evidence `sufficient`, `insufficient` or `contradictory`, and the deterministic validator can override it (rules in `orchestration/validation.py`).
- **Insufficient** → a *search revision*: Search runs new directive queries and excludes papers already seen.
- **Contradictory** with a scope change → a *scope revision*: the Planner writes plan v+1.
- Every replan reason must be backed by the decision (`ReplanningRequest.check_against`).

**How is the loop bounded?**
- At most 3 iterations, 60 LLM calls and 200k tokens per run; replanning never resets the budget.
- Before another iteration the router checks it can afford one; otherwise the run goes to `limit_reached` → Writer.
- Recursion limit 40, timeout 20 min.

**How are hallucinated citations controlled?**
- References are **built by code from paper metadata**; the LLM only places `[@Pn]` keys.
- The contract rejects a citation key without a reference, and the Writer gets one retry for invented keys.

**How are claims grounded?**
- Each evidence item needs a **verbatim quote**, checked against the source text after normalisation.
- Ungrounded quotes are dropped and counted, with one retry per paper.
- Abstract-only evidence is capped at confidence 0.6.

**How are documents retrieved safely?**
- Only provider-reported open-access PDF URLs are fetched, and landing pages are never scraped.
- The SSRF checks run on every redirect hop: public IPs only, no https → http downgrade, PDF signature, 15 MB and 30 s limits.
- Files are kept in memory only, and pypdf runs with a deadline.

**What if a paper can't be retrieved?**
It's analysed from its abstract (or as metadata-only with no LLM call if there is no abstract). The reason is recorded, and the other papers continue.

**What if an LLM fails or rate-limits?**
- ≤ 2 retries honouring `Retry-After`, then fallback to the next model or provider. Every attempt and fallback is in the trace.
- Malformed output gets one repair round.
- Fatal failures end the run as `failed` (or `partial` if a synthesis exists) with a safe error code.

**How are user API keys protected?**
- Encrypted with MultiFernet; only the last 4 characters are ever returned.
- Decrypted per request inside the provider adapter, and never in graph state, traces, logs or responses (tested in `tests/test_research_secrets.py`).
- Never in the frontend or in environment variables.

**How is user data isolated?**
Every query is scoped to the session's user. Another user's run returns 404 for detail, events, outputs, result and cancel. This was tested in the suite and verified in production.

**Why LangGraph?**
Typed state with append-only reducers, conditional edges for the adaptive loop, a recursion limit, and pure route functions that are easy to unit-test. It's used without LangSmith or LangChain model wrappers.

**Why Groq and Gemini?**
Both have free tiers that need no billing, and the app works with either or both. Role preferences: Groq for the fast, high-volume steps; Gemini for synthesis and writing. Each falls back to the other.

**Why OpenAlex and Semantic Scholar?**
Free, open scholarly APIs with abstracts, DOIs and open-access PDF links. Two sources give coverage and redundancy; the search degrades to one if the other fails.

**Why Render, Vercel and Neon?**
All free tiers with no billing (a hard project constraint). Vercel suits Next.js, Render runs the existing Docker image, and Neon is managed PostgreSQL.

**What happens if Render sleeps?**
The first request takes about 30–60 s. The UI shows "waking the research engine" with elapsed time and continues on its own, without inventing progress.

**What happens if a run is interrupted?**
Runs execute in the API process. After a restart, the startup sweep marks unfinished runs `failed: interrupted`, and everything recorded before that is kept.

**How was the system tested?**
- **Backend:** pytest, 388 tests against real PostgreSQL. They cover contracts, LLM adapters (mocked HTTP), tools (mock transports, PDF fixtures, an SSRF matrix), each agent with a scripted LLM, full-graph adaptive paths, the Runs API end to end, auth, credentials, migrations and secret leakage. Ruff and mypy (strict) also run.
- **Frontend:** 40 `node:test` tests, plus lint, typecheck and build.
- **CI:** all of these run in GitHub Actions, along with gitleaks.

**What real execution evidence exists?**
- Two exported traces in `docs/traces/`:
  - `34908068`: search revision, then the budget limit.
  - `d29bb92b`: search revision, then sufficient.
- The production run `9403b69c`: two search revisions, then the iteration limit.
- The failed and partial local runs from Phase 7 (documented in `docs/PHASE7_RUNS_API.md`).

**Current limitations?**
- Free-tier cold starts, and in-process runs that a restart interrupts.
- Groq tokens-per-minute 429s count toward the call budget.
- Free model availability changes over time.
- Exact-DOI deduplication counts versions of one paper separately.
- Polling rather than streaming.
- No Playwright end-to-end test.
- A real contradictory → scope-revision run has not occurred; that path is test-only.
