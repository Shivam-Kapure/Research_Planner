import assert from "node:assert/strict";
import { beforeEach, describe, test } from "node:test";
import { ApiError } from "@/lib/api/client";
import { EVENTS_PAGE } from "@/lib/api/endpoints";
import type { AgentOutput, RunDetail, RunResult, RunStatus, TraceEvent } from "@/lib/api/types";
import { RunPoller, type RunSnapshot } from "@/lib/runs/poller";
import { event, resetSeq, runDetail } from "./fixtures";

/** A scripted backend: each poll round returns the next status and the events written since. */
function scriptedApi(rounds: { status: RunStatus; events: TraceEvent[] }[]) {
  const all: TraceEvent[] = [];
  const calls: string[] = [];
  let round = -1;
  const api = {
    async getRun(): Promise<RunDetail> {
      round = Math.min(round + 1, rounds.length - 1);
      all.push(...rounds[round].events.filter((e) => !all.includes(e)));
      calls.push(`run:${rounds[round].status}`);
      return runDetail({ status: rounds[round].status });
    },
    async events(_id: string, after: number): Promise<TraceEvent[]> {
      calls.push(`events:after=${after}`);
      return all.filter((e) => e.seq > after).slice(0, EVENTS_PAGE);
    },
    async outputs(): Promise<AgentOutput[]> {
      calls.push("outputs");
      return [];
    },
    async result(): Promise<RunResult> {
      calls.push("result");
      return { run_id: "run-1", status: rounds[round].status, stop_reason: null, review: null, synthesis: null, error: null };
    },
  };
  return { api, calls };
}

const noSleep = { sleep: async () => undefined, isHidden: () => false };

describe("RunPoller", () => {
  beforeEach(resetSeq);

  test("uses the after cursor, re-reads outputs only on new completions, and stops when terminal", async () => {
    const e1 = event({ agent: "orchestrator", event_type: "run_started" });
    const e2 = event({ agent: "planner", event_type: "agent_started" });
    const e3 = event({ agent: "planner", event_type: "llm_call" });
    const e4 = event({ agent: "planner", event_type: "agent_completed", output_ref: "out-1" });
    const e5 = event({ agent: "orchestrator", event_type: "run_completed" });
    const { api, calls } = scriptedApi([
      { status: "running", events: [e1, e2] },
      { status: "running", events: [e3] },
      { status: "running", events: [e4] },
      { status: "completed", events: [e5] },
    ]);
    const snapshots: RunSnapshot[] = [];
    const poller = new RunPoller(api, "run-1", (s) => snapshots.push(s), noSleep);
    await poller.start();

    assert.deepEqual(calls, [
      "run:running",
      "events:after=0",
      "outputs", // first look at a live run
      "run:running",
      "events:after=2",
      "run:running",
      "events:after=3",
      "outputs", // agent_completed with an output_ref arrived
      "run:completed",
      "events:after=4",
      "result",
      "outputs",
    ]);
    const final = poller.current;
    assert.equal(final.settled, true);
    assert.deepEqual(
      final.events.map((e) => e.seq),
      [1, 2, 3, 4, 5],
    );
    assert.equal(final.run?.status, "completed");
    assert.ok(final.result);
  });

  test("pages through a long trace without waiting between pages", async () => {
    const many = Array.from({ length: EVENTS_PAGE + 5 }, () => event({ agent: "analysis", event_type: "llm_call" }));
    const { api, calls } = scriptedApi([{ status: "completed", events: many }]);
    const poller = new RunPoller(api, "run-1", () => undefined, noSleep);
    await poller.start();
    assert.deepEqual(calls.slice(0, 3), ["run:completed", "events:after=0", `events:after=${EVENTS_PAGE}`]);
    assert.equal(poller.current.events.length, EVENTS_PAGE + 5);
  });

  test("backs off on transient failures and recovers", async () => {
    const { api } = scriptedApi([{ status: "completed", events: [] }]);
    let failures = 2;
    const flaky = {
      ...api,
      getRun: async () => {
        if (failures-- > 0) throw new ApiError("unavailable", 503, "waking");
        return api.getRun();
      },
    };
    const delays: number[] = [];
    const seen: (ApiError | null)[] = [];
    const poller = new RunPoller(flaky, "run-1", (s) => seen.push(s.connectionError), {
      intervalMs: 1000,
      isHidden: () => false,
      sleep: async (ms) => {
        delays.push(ms);
      },
    });
    await poller.start();
    assert.deepEqual(delays, [2000, 4000]);
    assert.equal(seen[0]?.kind, "unavailable");
    assert.equal(poller.current.connectionError, null);
    assert.equal(poller.current.settled, true);
  });

  test("stops on a 404 instead of retrying", async () => {
    let calls = 0;
    const api = {
      getRun: async (): Promise<RunDetail> => {
        calls += 1;
        throw new ApiError("not_found", 404, "Run not found");
      },
      events: async () => [],
      outputs: async () => [],
      result: async () => {
        throw new Error("unreachable");
      },
    };
    const poller = new RunPoller(api, "missing", () => undefined, noSleep);
    await poller.start();
    assert.equal(calls, 1);
    assert.equal(poller.current.fatalError?.kind, "not_found");
  });

  test("polls less often while the tab is hidden", async () => {
    const { api } = scriptedApi([
      { status: "running", events: [] },
      { status: "completed", events: [] },
    ]);
    const delays: number[] = [];
    const poller = new RunPoller(api, "run-1", () => undefined, {
      intervalMs: 2000,
      hiddenIntervalMs: 10000,
      isHidden: () => true,
      sleep: async (ms) => {
        delays.push(ms);
      },
    });
    await poller.start();
    assert.deepEqual(delays, [10000]);
  });
});
