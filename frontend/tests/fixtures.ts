import { readFileSync } from "node:fs";
import path from "node:path";
import type { AgentOutput, RunDetail, RunResult, TraceEvent } from "@/lib/api/types";

/** The unedited export of the first real run (docs/traces/), used read-only as test input. */
export type RealRun = { run: RunDetail; events: TraceEvent[]; outputs: AgentOutput[]; result: RunResult };

let cached: RealRun | null = null;

export function realRun(): RealRun {
  if (!cached) {
    // .test-build/tests → repository root
    const file = path.join(__dirname, "..", "..", "..", "docs", "traces", "2026-10-07_run-34908068.json");
    cached = JSON.parse(readFileSync(file, "utf8")) as RealRun;
  }
  return structuredClone(cached);
}

let seq = 0;

/** A synthetic trace event for scenarios the real run did not take (e.g. a scope revision). */
export function event(partial: Partial<TraceEvent> & Pick<TraceEvent, "agent" | "event_type">): TraceEvent {
  seq += 1;
  return {
    id: partial.id ?? `e${seq}`,
    run_id: "run-1",
    seq: partial.seq ?? seq,
    ts: partial.ts ?? new Date(Date.UTC(2026, 9, 7, 12, 0, seq)).toISOString(),
    iteration: partial.iteration ?? 1,
    status: "ok",
    message: partial.message ?? `${partial.agent} ${partial.event_type}`,
    parent_id: null,
    input_ref: null,
    output_ref: null,
    tool: null,
    decision: null,
    validation: null,
    llm: null,
    error: null,
    ...partial,
  };
}

export function resetSeq(): void {
  seq = 0;
}

/** A node's start, optional children, completion and handoff, parented like the backend does. */
export function node(
  agent: TraceEvent["agent"],
  iteration: number,
  summary: string,
  children: Partial<TraceEvent>[] = [],
): TraceEvent[] {
  const start = event({ agent, event_type: "agent_started", iteration, message: `${agent} started (iteration ${iteration})` });
  const kids = children.map((c) =>
    event({ agent, iteration, parent_id: start.id, event_type: "decision", ...c } as TraceEvent),
  );
  const done = event({
    agent,
    iteration: kids.at(-1)?.iteration ?? iteration,
    event_type: "agent_completed",
    parent_id: start.id,
    message: `${agent}: ${summary}`,
    output_ref: agent === "orchestrator" ? null : `out-${start.id}`,
  });
  return [start, ...kids, done];
}

export function runDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: "run-1",
    question: "Does regular aerobic exercise lower blood pressure in adults with hypertension?",
    status: "running",
    iteration: 1,
    stop_reason: null,
    created_at: "2026-10-07T12:00:00Z",
    updated_at: "2026-10-07T12:00:00Z",
    completed_at: null,
    request: { question: "q", max_iterations: 3, year_from: null, year_to: null },
    started_at: "2026-10-07T12:00:00Z",
    error: null,
    progress: { iteration: 1, max_iterations: 3, llm_calls: 0, max_llm_calls: 60, tokens_used: 0, max_tokens: 200000 },
    ...overrides,
  };
}
