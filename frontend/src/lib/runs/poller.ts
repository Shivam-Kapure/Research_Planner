import { ApiError } from "../api/client";
import { EVENTS_PAGE, type Api } from "../api/endpoints";
import type { AgentOutput, RunDetail, RunResult, TraceEvent } from "../api/types";
import { mergeEvents } from "../trace/timeline";
import { isTerminal } from "./status";

export type RunSnapshot = {
  run: RunDetail | null;
  events: TraceEvent[];
  outputs: AgentOutput[] | null;
  result: RunResult | null;
  /** True once the run is terminal and its result and outputs have been loaded. */
  settled: boolean;
  /** Set while polls fail transiently (connection lost, backend waking); cleared on success. */
  connectionError: ApiError | null;
  /** A permanent failure (e.g. 404 or 401): polling has stopped. */
  fatalError: ApiError | null;
};

export type PollerOptions = {
  intervalMs?: number;
  hiddenIntervalMs?: number;
  maxBackoffMs?: number;
  isHidden?: () => boolean;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
};

type PollApi = Pick<Api, "getRun" | "events" | "outputs" | "result">;

const defaultSleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });

/**
 * Polls one run (docs/PHASE7_RUNS_API.md, "Frontend integration"):
 * - GET /runs/{id} for status, then GET /events?after=<last seq> for only the new trace events;
 * - outputs are re-read only when a new agent_completed event references a persisted output;
 * - once the status is terminal: a final events read, then /result and /outputs, then stop.
 * Transient failures back off exponentially; 401/404 stop polling.
 */
export class RunPoller {
  private snapshot: RunSnapshot = {
    run: null,
    events: [],
    outputs: null,
    result: null,
    settled: false,
    connectionError: null,
    fatalError: null,
  };
  private controller: AbortController | null = null;
  private failures = 0;
  private readonly interval: number;
  private readonly hiddenInterval: number;
  private readonly maxBackoff: number;
  private readonly isHidden: () => boolean;
  private readonly sleep: (ms: number, signal: AbortSignal) => Promise<void>;

  constructor(
    private readonly api: PollApi,
    private readonly runId: string,
    private readonly onChange: (snapshot: RunSnapshot) => void,
    options: PollerOptions = {},
  ) {
    this.interval = options.intervalMs ?? 2000;
    this.hiddenInterval = options.hiddenIntervalMs ?? 10000;
    this.maxBackoff = options.maxBackoffMs ?? 30000;
    this.isHidden = options.isHidden ?? (() => typeof document !== "undefined" && document.hidden);
    this.sleep = options.sleep ?? defaultSleep;
  }

  get current(): RunSnapshot {
    return this.snapshot;
  }

  /** Runs until the run settles, a fatal error occurs, or stop() is called. */
  async start(): Promise<void> {
    this.stop();
    const controller = new AbortController();
    this.controller = controller;
    const { signal } = controller;
    while (!signal.aborted) {
      try {
        await this.tick(signal);
        this.failures = 0;
        if (this.snapshot.connectionError) this.update({ connectionError: null });
      } catch (error) {
        if (signal.aborted) return;
        if (error instanceof ApiError && !error.transient && error.kind !== "server") {
          this.update({ fatalError: error, connectionError: null });
          return;
        }
        this.failures += 1;
        const failure = error instanceof ApiError ? error : new ApiError("unavailable", 0, "Connection lost.");
        this.update({ connectionError: failure });
      }
      if (this.snapshot.settled || signal.aborted) return;
      await this.sleep(this.nextDelay(), signal);
    }
  }

  stop(): void {
    this.controller?.abort();
    this.controller = null;
  }

  private nextDelay(): number {
    if (this.failures > 0) {
      return Math.min(this.maxBackoff, this.interval * 2 ** Math.min(this.failures, 5));
    }
    return this.isHidden() ? this.hiddenInterval : this.interval;
  }

  private update(patch: Partial<RunSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    this.onChange(this.snapshot);
  }

  private lastSeq(): number {
    const events = this.snapshot.events;
    return events.length ? events[events.length - 1].seq : 0;
  }

  private async tick(signal: AbortSignal): Promise<void> {
    // Status first: once it reads terminal, every event of the run has already been written.
    const run = await this.api.getRun(this.runId, signal);
    const before = this.lastSeq();
    let events = this.snapshot.events;
    for (;;) {
      const page = await this.api.events(this.runId, events.length ? events[events.length - 1].seq : 0, signal);
      events = mergeEvents(events, page);
      if (page.length < EVENTS_PAGE) break;
    }
    const fresh = events.filter((e) => e.seq > before);
    const newOutput = fresh.some((e) => e.event_type === "agent_completed" && e.output_ref);
    this.update({ run, events });

    if (isTerminal(run.status)) {
      const [result, outputs] = await Promise.all([
        this.api.result(this.runId, signal),
        this.api.outputs(this.runId, signal),
      ]);
      this.update({ result, outputs, settled: true });
      return;
    }
    if (newOutput || this.snapshot.outputs === null) {
      this.update({ outputs: await this.api.outputs(this.runId, signal) });
    }
  }
}
