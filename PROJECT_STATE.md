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

- Database: Neon PostgreSQL
- Frontend hosting: Vercel
- Backend hosting: Railway or Render
- LLM providers: user-provided Groq and Gemini API keys, supplied after authentication (never stored in the repo)
- Frontend: a polished, intentionally designed research product (visual inspiration will be provided in the frontend phase)

## CA3 Evidence Required

At least 4 distinct agents, clear responsibilities, planning/reasoning/tool use/adaptation, inter-agent coordination, adaptive replanning, architecture and data-flow docs, precise I/O definitions, robust error handling, real automated tests, clean repo structure, meaningful incremental commits, real execution traces of agent handoffs.

## Current Phase

**Phase 0: project setup and rules.** No application code exists yet.

## Postponed to Phase 1

- Final technology stack (language, backend framework, frontend framework)
- Agent orchestration approach/framework
- Literature source APIs and tools
- Inter-agent message schemas and I/O contracts
- Data model and persistence design
- Authentication approach and API-key handling
- Testing frameworks and strategy
- Repository/folder structure

## Upcoming Phases (tentative)

1. Phase 1: stack comparison against CA3, architecture, data flow, I/O contracts
2. Phase 2: backend foundation, database and auth
3. Phase 3: agent implementation and orchestration, including the replanning loop
4. Phase 4: automated tests and execution tracing
5. Phase 5: frontend
6. Phase 6: deployment, final documentation and CA3 evidence
