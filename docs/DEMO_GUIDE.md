# Demo Guide (5–10 minutes)

**Production app:** https://researchpilot-rho.vercel.app. The backend is https://researchpilot-api-78oo.onrender.com.

## Before the demo

1. **Wake the backend 2–3 minutes early.** Open https://researchpilot-api-78oo.onrender.com/readyz until it shows `{"status":"ready"}`. Render Free sleeps after about 15 idle minutes and takes 30–60 s to wake.
2. **Sign in with the account that owns the production run `9403b69c`.** Check that **Settings** shows Groq and Gemini as **Verified**.
3. **Decide whether to start a new run live.** A run takes about 5–8 minutes and uses free-tier LLM quota. Whether it replans depends on the real evidence, so it can't be scripted. **The safe default is to show the existing real run `9403b69c`**, which replanned twice, and to start a live run only if there's time.
4. **Keep [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) open on a second tab** for the diagram.

## Flow

| # | Show | Say |
|---|---|---|
| 1 | Landing page | "ResearchPilot turns a question into a cited literature review using five coordinated agents." Scroll to *The agents* and *The process*. |
| 2 | Architecture diagram ([FINAL_ARCHITECTURE §2](FINAL_ARCHITECTURE.md#2-architecture-diagram)) | Vercel → Render (FastAPI + LangGraph) → Neon; agents call OpenAlex/Semantic Scholar, open-access PDFs, Groq and Gemini. The loop back from Evidence Synthesis is the agentic part. |
| 3 | **Register / Sign in** | Session in an `HttpOnly`, `Secure` cookie; there are no tokens in the browser's storage. |
| 4 | **Settings** | Keys are masked to the last 4 characters and verified with the provider on save. They're stored encrypted (MultiFernet) on the server and never returned. Users bring their own free-tier keys. |
| 5 | **New research** | Type a focused question, choose iterations (1–3) and an optional year range. *(Optional: start a live run here, or skip to step 7.)* |
| 6 | Live run → **Execution** tab | The active step pulses and polling reads only new trace events (`after=<seq>`). Point at the **Research Planner** (plan with sub-questions), **Literature Search** (queries, sources), **Document Analysis** (full text vs abstract only, provider fallbacks) and **Evidence Synthesis** (verdict). |
| 7 | **History → run `9403b69c`** | The banner at the top states the outcome and confidence first: *Completed with limitations · Evidence limited*, stopped at the iteration limit. |
| 8 | **Overview** | "The path the agents took": Synthesis *insufficient* → **Replanning (search revision)** twice → Synthesis *insufficient, limit reached* → Writer. This is drawn from real trace events, not a fixed diagram. Then the figures: 3 iterations, 15 papers, 15 documents (4 full text), 17 evidence items, 41/60 model calls. |
| 9 | **Execution** | Expand a Replanning step: the reasons are tied to specific weak sub-questions, and the next iteration's searches target them. Open *Trace detail* for tool calls, model calls (including 429 retries and fallbacks) and validations. |
| 10 | **Evidence** | Per iteration: verdict, coverage per sub-question (covered / weak / missing), themes, and the replanning request with its new search directions. |
| 11 | **Review** | Article layout; click a `[P2]` citation to jump to its reference with DOI. Point out the **Limitations** box (5 items, including the iteration limit and abstract-only evidence). |
| 12 | **Agent outputs** | The stored contracts per iteration: plan, search results, each paper's analysis with **verbatim quotes**, synthesis decisions and the final review, plus the raw JSON. |
| 13 | **History** | Every run with its status; other users can't see them (isolation was verified in production). |
| 14 | Deployment | Vercel Hobby + Render Free (Docker) + Neon Free; health at `/healthz`, readiness at `/readyz`. |
| 15 | Security | Argon2id, opaque sessions, HttpOnly/Secure cookies, origin check, encrypted keys, trace redaction, the SSRF-safe PDF fetcher, HTTPS + HSTS, gitleaks. |
| 16 | Free-tier limits | Cold starts, in-process runs (a restart marks a run interrupted), Groq tokens-per-minute 429s, model churn. All of these are visible in the trace, not hidden. |

## If replanning doesn't happen in a live run

That's a genuine outcome: the evidence was judged sufficient on the first pass. Show the replanning in the real production run `9403b69c` (two search revisions), and in the exported real trace [`2026-10-07_run-d29bb92b.json`](traces/2026-10-07_run-d29bb92b.json) (insufficient → search revision → sufficient). The **scope revision** path (contradictory → Planner) is covered by the automated graph test `backend/tests/test_research_graph.py`; no real run has triggered it.

## If something fails during the demo

- **Waking screen:** wait. It shows elapsed time and continues on its own.
- **A run fails:** open the red banner and the Execution tab. The failure is traced with a safe error code, which also demonstrates bounded failure handling.
- **"A run is already in progress":** only one active run per user is allowed. Open it from the notice.
