# Screenshot Checklist

All screenshots are **TO CAPTURE** manually from the real application. Nothing is committed yet, and none may be edited or mocked.

Suggested location: `docs/screenshots/`, named as below. Before saving, check that each image shows no full API key, password, cookie or connection string.

| # | Screenshot | Where | File |
|---|---|---|---|
| 1 | Landing page (hero and agents) | `/` | `01-landing.png` |
| 2 | Research workspace with a question typed | `/research` | `02-workspace.png` |
| 3 | Settings with masked, verified provider keys | `/settings` | `03-settings-masked.png` |
| 4 | Live run: Research Planner in progress | `/runs/<id>` → Execution | `04-live-planner.png` |
| 5 | Literature Search step with trace detail (queries) | Execution | `05-search.png` |
| 6 | Document Analysis step (full text vs abstract only, fallbacks) | Execution | `06-analysis.png` |
| 7 | Evidence Synthesis verdict callout | Execution | `07-synthesis.png` |
| 8 | **Replanning** callout (search revision and its reasons) | Execution, run `9403b69c` | `08-replanning.png` |
| 9 | Overview "path the agents took" with replanning | Overview, run `9403b69c` | `09-agent-path.png` |
| 10 | Final review (title, status, limitations) | Review | `10-review.png` |
| 11 | Citations and references with DOIs | Review (bottom) | `11-references.png` |
| 12 | Agent outputs (an analysis with verbatim quotes) | Agent outputs | `12-agent-outputs.png` |
| 13 | Run history | `/runs` | `13-history.png` |
| 14 | Production deployment: Render service Live, Vercel deployment Ready, `/readyz` response | dashboards and browser | `14-deployment.png` |
| 15 | Architecture diagram (rendered Mermaid) | [FINAL_ARCHITECTURE.md](FINAL_ARCHITECTURE.md) on GitHub | `15-architecture.png` |
| 16 | GitHub repository and a green CI run | GitHub → Actions | `16-ci.png` |
| 17 | A real trace file | `docs/traces/2026-10-07_run-d29bb92b.json` (a replan event) | `17-trace.png` |
| 18 | Cold start: waking screen (optional, after ~15 min idle) | any workspace page | `18-cold-start.png` |

**Optional evidence (TO DO manually):** export the production run `9403b69c` while signed in as its owner. Save the JSON responses of these four endpoints, unedited, to `docs/traces/2026-10-08_run-9403b69c/`:
- `/api/runs/9403b69c-77f9-4fe5-b08e-f2d44662cc06`
- `…/events?limit=200` (repeat with `&after=<last seq>` while 200 events come back)
- `…/outputs`
- `…/result`
