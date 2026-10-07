import type { TraceEvent } from "../api/types";
import { humanize } from "../format";

// Turns the append-only trace (GET /api/runs/{id}/events) into the steps the UI shows. Nothing
// here assumes a fixed pipeline: steps, iterations, verdicts, replanning and limits all come
// from recorded events. The trace model is documented in docs/PHASE6_MULTI_AGENT.md ("Trace
// model"): every graph node records agent_started, its child events (parent_id = the start
// event), agent_completed and a handoff; the orchestrator records routing and replan events.

export type NodeName =
  | "planner"
  | "literature_search"
  | "document_analysis"
  | "evidence_synthesis"
  | "replanning"
  | "review_writer";

/** Trace `agent` values → graph nodes. The replanning node is recorded as "orchestrator". */
const NODE_BY_AGENT: Record<string, NodeName> = {
  planner: "planner",
  search: "literature_search",
  analysis: "document_analysis",
  synthesis: "evidence_synthesis",
  orchestrator: "replanning",
  writer: "review_writer",
};

export const NODE_LABEL: Record<NodeName, string> = {
  planner: "Research Planner",
  literature_search: "Literature Search",
  document_analysis: "Document Analysis",
  evidence_synthesis: "Evidence Synthesis",
  replanning: "Replanning",
  review_writer: "Review Writer",
};

export const NODE_SHORT: Record<NodeName, string> = {
  planner: "Planner",
  literature_search: "Search",
  document_analysis: "Analysis",
  evidence_synthesis: "Synthesis",
  replanning: "Replanning",
  review_writer: "Writer",
};

export type StepState = "active" | "completed" | "failed" | "stopped";

export type Route = {
  /** "writer", "replanning" or "limit_reached" (routing after synthesis). */
  route: string;
  rationale: string;
  stopReason: string | null;
};

export type Replan = {
  kind: string; // "search_revision" | "scope_revision"
  reasons: string[];
  toNode: NodeName | null;
  nextIteration: number;
};

export type Step = {
  id: string; // the agent_started event id
  node: NodeName;
  agent: string;
  iteration: number;
  startedAt: string;
  endedAt: string | null;
  state: StepState;
  summary: string | null;
  outputRef: string | null;
  events: TraceEvent[]; // every child event, in seq order
  tools: TraceEvent[];
  llmCalls: TraceEvent[];
  validations: TraceEvent[];
  fallbacks: TraceEvent[];
  errors: TraceEvent[];
  verdict: { verdict: string; rationale: string } | null;
  overrides: string[];
  route: Route | null;
  replan: Replan | null;
  tokens: number;
};

export type IterationGroup = { iteration: number; steps: Step[] };

export type Timeline = {
  runStarted: TraceEvent | null;
  runCompleted: TraceEvent | null;
  steps: Step[];
  iterations: IterationGroup[];
  /** The step still in progress, if the run is live. */
  current: Step | null;
  /** Run-level events that belong to no step (e.g. a fatal error outside a node). */
  runEvents: TraceEvent[];
  lastSeq: number;
};

const stripNodePrefix = (message: string) => message.replace(/^[a-z_]+:\s*/, "");

function newStep(start: TraceEvent): Step {
  return {
    id: start.id,
    node: NODE_BY_AGENT[start.agent] ?? "replanning",
    agent: start.agent,
    iteration: start.iteration,
    startedAt: start.ts,
    endedAt: null,
    state: "active",
    summary: null,
    outputRef: null,
    events: [],
    tools: [],
    llmCalls: [],
    validations: [],
    fallbacks: [],
    errors: [],
    verdict: null,
    overrides: [],
    route: null,
    replan: null,
    tokens: 0,
  };
}

function attach(step: Step, event: TraceEvent): void {
  step.events.push(event);
  switch (event.event_type) {
    case "tool_call":
    case "tool_result":
      step.tools.push(event);
      break;
    case "llm_call":
      step.llmCalls.push(event);
      step.tokens += (event.llm?.tokens_in ?? 0) + (event.llm?.tokens_out ?? 0);
      break;
    case "validation":
      step.validations.push(event);
      if (event.validation?.override) step.overrides.push(event.validation.override);
      break;
    case "fallback":
      step.fallbacks.push(event);
      break;
    case "error":
      step.errors.push(event);
      break;
    case "decision":
      if (!event.decision) break;
      if (event.agent === "orchestrator") {
        const stop = /stop_reason=([a-z_]+)/.exec(event.decision.rationale);
        step.route = {
          route: event.decision.route,
          rationale: event.decision.rationale,
          stopReason: stop ? stop[1] : null,
        };
      } else {
        step.verdict = { verdict: event.decision.route, rationale: event.decision.rationale };
      }
      break;
    case "replan":
      if (!event.decision) break;
      step.replan = {
        kind: event.decision.route,
        reasons: event.decision.rationale.split(/;\s+/).filter(Boolean),
        toNode: event.decision.to_agent ? (NODE_BY_AGENT[event.decision.to_agent] ?? null) : null,
        nextIteration: event.iteration,
      };
      break;
    case "agent_completed":
      step.endedAt = event.ts;
      step.state = event.status === "failed" ? "failed" : "completed";
      step.summary = stripNodePrefix(event.message);
      step.outputRef = event.output_ref;
      break;
    case "handoff":
      step.endedAt ??= event.ts;
      break;
  }
}

/** Merge newly polled events into the known list: ordered by seq, duplicates dropped. */
export function mergeEvents(known: TraceEvent[], incoming: TraceEvent[]): TraceEvent[] {
  if (!incoming.length) return known;
  const seen = new Set(known.map((e) => e.seq));
  const fresh = incoming.filter((e) => !seen.has(e.seq));
  if (!fresh.length) return known;
  return [...known, ...fresh].sort((a, b) => a.seq - b.seq);
}

export function deriveTimeline(events: TraceEvent[], runFinished: boolean): Timeline {
  const ordered = [...events].sort((a, b) => a.seq - b.seq);
  const byStartId = new Map<string, Step>();
  const steps: Step[] = [];
  const runEvents: TraceEvent[] = [];
  let runStarted: TraceEvent | null = null;
  let runCompleted: TraceEvent | null = null;
  let open: Step | null = null;

  for (const event of ordered) {
    if (event.event_type === "run_started") {
      runStarted = event;
      continue;
    }
    if (event.event_type === "run_completed") {
      runCompleted = event;
      continue;
    }
    if (event.event_type === "agent_started") {
      const step = newStep(event);
      steps.push(step);
      byStartId.set(event.id, step);
      open = step;
      continue;
    }
    // Children name their start event; anything unparented belongs to the node in progress
    // (nodes run one at a time), or to the run itself.
    const owner = (event.parent_id && byStartId.get(event.parent_id)) || open;
    if (owner) attach(owner, event);
    else runEvents.push(event);
  }

  const finished = runFinished || runCompleted !== null;
  for (const step of steps) {
    if (step.state === "active" && finished) step.state = "stopped";
  }

  const iterations: IterationGroup[] = [];
  for (const step of steps) {
    const last = iterations[iterations.length - 1];
    if (last && last.iteration === step.iteration) last.steps.push(step);
    else iterations.push({ iteration: step.iteration, steps: [step] });
  }

  const current = steps.length && steps[steps.length - 1].state === "active" ? steps[steps.length - 1] : null;

  return {
    runStarted,
    runCompleted,
    steps,
    iterations,
    current,
    runEvents,
    lastSeq: ordered.length ? ordered[ordered.length - 1].seq : 0,
  };
}

// ---- Small readers over tool events (formats from backend/app/agents/*) ----

/** "mode=full_text reason=None pages=11 host=…" → { mode: "full_text", reason: null, … } */
export function parseSummary(summary: string | null): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  if (!summary) return out;
  for (const match of summary.matchAll(/([a-z_]+)=(\S+)/g)) {
    out[match[1]] = match[2] === "None" ? null : match[2];
  }
  return out;
}

export type DocumentCounts = { fullText: number; abstractOnly: number; unavailable: number };

export function documentCounts(steps: Step[]): DocumentCounts {
  const counts: DocumentCounts = { fullText: 0, abstractOnly: 0, unavailable: 0 };
  for (const step of steps) {
    for (const tool of step.tools) {
      if (tool.tool?.name !== "retrieve_document") continue;
      const mode = parseSummary(tool.tool.result_summary).mode;
      if (mode === "full_text") counts.fullText += 1;
      else if (mode === "abstract_only") counts.abstractOnly += 1;
      else counts.unavailable += 1;
    }
  }
  return counts;
}

/** A short, human description of one recorded event (used for a live step's latest activity). */
export function describeEvent(event: TraceEvent): string {
  const tool = event.tool;
  if (tool?.name === "literature_search" && typeof tool.args.query === "string") {
    return `Searched “${tool.args.query}”`;
  }
  if (tool?.name === "retrieve_document" && typeof tool.args.paper_key === "string") {
    const mode = parseSummary(tool.result_summary).mode;
    return `Retrieved ${tool.args.paper_key}${mode ? ` (${mode.replaceAll("_", " ")})` : ""}`;
  }
  if (event.llm) {
    const outcome = event.llm.outcome === "ok" ? "answered" : event.llm.outcome.replaceAll("_", " ");
    return `Model ${event.llm.provider}/${event.llm.model} ${outcome}`;
  }
  if (event.validation) {
    return `${humanize(event.validation.schema_name)} ${event.validation.passed ? "validated" : "failed validation"}`;
  }
  return humanize(stripNodePrefix(event.message));
}

export const searchCalls = (step: Step) => step.tools.filter((t) => t.tool?.name === "literature_search");

export const failedLlmCalls = (step: Step) => step.llmCalls.filter((e) => e.llm && e.llm.outcome !== "ok");

export function durationMs(step: Step): number | null {
  if (!step.endedAt) return null;
  return Math.max(0, Date.parse(step.endedAt) - Date.parse(step.startedAt));
}
