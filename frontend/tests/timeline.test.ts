import assert from "node:assert/strict";
import { beforeEach, describe, test } from "node:test";
import { deriveTimeline, documentCounts, mergeEvents } from "@/lib/trace/timeline";
import { event, node, realRun, resetSeq } from "./fixtures";

describe("deriveTimeline on the real run 34908068", () => {
  const { events } = realRun();
  const timeline = deriveTimeline(events, true);

  test("follows the recorded path, including the replanning loop and the limit stop", () => {
    assert.deepEqual(
      timeline.steps.map((s) => s.node),
      [
        "planner",
        "literature_search",
        "document_analysis",
        "evidence_synthesis",
        "replanning",
        "literature_search",
        "document_analysis",
        "evidence_synthesis",
        "review_writer",
      ],
    );
    assert.deepEqual(
      timeline.iterations.map((g) => [g.iteration, g.steps.length]),
      [
        [1, 5],
        [2, 4],
      ],
    );
  });

  test("reads verdicts, the replan and the budget stop from the trace", () => {
    const syntheses = timeline.steps.filter((s) => s.node === "evidence_synthesis");
    assert.deepEqual(
      syntheses.map((s) => s.verdict?.verdict),
      ["insufficient", "insufficient"],
    );
    assert.equal(syntheses[0].route?.route, "replanning");
    assert.equal(syntheses[1].route?.route, "limit_reached");
    assert.equal(syntheses[1].route?.stopReason, "budget_limit");

    const replan = timeline.steps.find((s) => s.node === "replanning")?.replan;
    assert.equal(replan?.kind, "search_revision");
    assert.equal(replan?.toNode, "literature_search");
    assert.equal(replan?.nextIteration, 2);
    assert.equal(replan?.reasons.length, 3);
    assert.match(replan!.reasons[0], /^low_quality sq-1: weak/);
  });

  test("attaches every event to a step or the run, and counts tool use", () => {
    const attached = timeline.steps.reduce((n, s) => n + 1 + s.events.length, 0);
    assert.equal(attached + 2, events.length); // + run_started and run_completed
    assert.equal(timeline.runEvents.length, 0);
    assert.ok(timeline.steps.every((s) => s.state === "completed"));
    assert.equal(timeline.current, null);
    assert.equal(timeline.lastSeq, 125);
    assert.deepEqual(documentCounts(timeline.steps), { fullText: 4, abstractOnly: 8, unavailable: 0 });
    assert.equal(timeline.steps[1].tools.length, 6);
    assert.equal(timeline.steps.reduce((n, s) => n + s.llmCalls.length, 0), 48);
  });

  test("a live prefix of the trace has one active step and no completion", () => {
    const live = deriveTimeline(
      events.filter((e) => e.seq <= 30),
      false,
    );
    assert.equal(live.current?.node, "document_analysis");
    assert.equal(live.steps.at(-1)?.state, "active");
    assert.equal(live.runCompleted, null);
    // The same prefix after the run ended (e.g. cancelled): the open step is shown as stopped.
    assert.equal(deriveTimeline(events.filter((e) => e.seq <= 30), true).steps.at(-1)?.state, "stopped");
  });
});

describe("deriveTimeline on synthetic paths", () => {
  beforeEach(resetSeq);

  test("a contradictory verdict that revises the scope returns to the planner", () => {
    const events = [
      event({ agent: "orchestrator", event_type: "run_started", message: "run started (max 3 iterations)" }),
      ...node("planner", 1, "plan v1 with 3 sub-questions"),
      ...node("search", 1, "6 papers selected"),
      ...node("analysis", 1, "6 papers analysed"),
      ...node("synthesis", 1, "verdict contradictory → replanning", [
        { decision: { route: "contradictory", rationale: "Studies disagree on sq-1.", from_agent: null, to_agent: null } },
        {
          agent: "orchestrator",
          decision: { route: "replanning", rationale: "verdict=contradictory, iteration 1/3", from_agent: "orchestrator", to_agent: "orchestrator" },
        },
      ]),
      ...node("orchestrator", 1, "scope_revision: starting iteration 2", [
        {
          event_type: "replan",
          iteration: 2,
          decision: { route: "scope_revision", rationale: "contradiction sq-1: trials disagree", from_agent: "orchestrator", to_agent: "planner" },
        },
      ]),
      ...node("planner", 2, "plan v2 with 3 sub-questions"),
    ];
    const timeline = deriveTimeline(events, false);
    assert.deepEqual(
      timeline.steps.map((s) => s.node),
      ["planner", "literature_search", "document_analysis", "evidence_synthesis", "replanning", "planner"],
    );
    const replan = timeline.steps[4].replan;
    assert.equal(replan?.kind, "scope_revision");
    assert.equal(replan?.toNode, "planner");
    assert.equal(timeline.steps[3].verdict?.verdict, "contradictory");
    assert.deepEqual(
      timeline.iterations.map((g) => g.iteration),
      [1, 2],
    );
  });

  test("a failed node and an unparented run error are both surfaced", () => {
    const start = event({ agent: "planner", event_type: "agent_started" });
    const events = [
      start,
      event({
        agent: "planner",
        event_type: "error",
        status: "failed",
        parent_id: start.id,
        error: { code: "no_provider_configured", message: "No LLM provider", retryable: false, attempt: null },
      }),
      event({ agent: "planner", event_type: "agent_completed", status: "failed", parent_id: start.id, message: "planner: failed" }),
      event({ agent: "orchestrator", event_type: "run_completed", message: "run failed" }),
    ];
    const timeline = deriveTimeline(events, true);
    assert.equal(timeline.steps[0].state, "failed");
    assert.equal(timeline.steps[0].errors[0].error?.code, "no_provider_configured");

    const orphan = event({ agent: "orchestrator", event_type: "error", status: "failed", message: "timeout" });
    assert.equal(deriveTimeline([orphan], true).runEvents.length, 1);
  });
});

describe("mergeEvents", () => {
  beforeEach(resetSeq);

  test("keeps seq order and ignores events it already has", () => {
    const [a, b, c] = [1, 2, 3].map((n) => event({ agent: "planner", event_type: "llm_call", seq: n }));
    const merged = mergeEvents([a, b], [b, c]);
    assert.deepEqual(
      merged.map((e) => e.seq),
      [1, 2, 3],
    );
    const same = [a];
    assert.equal(mergeEvents(same, [a]), same);
  });
});
