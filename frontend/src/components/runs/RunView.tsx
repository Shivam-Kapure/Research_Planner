"use client";

import Link from "next/link";
import { use, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { OutputsPanel } from "@/components/outputs/OutputsPanel";
import { Timeline } from "@/components/agents/Timeline";
import { EvidencePanel } from "@/components/results/EvidencePanel";
import { ReviewDocument } from "@/components/results/ReviewDocument";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { EmptyState, ErrorState, Loading, Notice } from "@/components/ui/feedback";
import { ApiError, errorMessage } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { FinalReview, RunDetail } from "@/lib/api/types";
import { formatDateTime, formatNumber } from "@/lib/format";
import { readOutputs } from "@/lib/runs/outputs";
import { isActive, isTerminal } from "@/lib/runs/status";
import { useRunPolling } from "@/lib/runs/useRunPolling";
import { deriveTimeline } from "@/lib/trace/timeline";
import { RunOverview } from "./RunOverview";
import { RunStatusBanner } from "./RunStatusBanner";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "execution", label: "Execution" },
  { id: "evidence", label: "Evidence" },
  { id: "review", label: "Review" },
  { id: "outputs", label: "Agent outputs" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const isTab = (value: string): value is TabId => TABS.some((t) => t.id === value);

export function RunView({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  const { snapshot, restart } = useRunPolling(runId);
  const { run, events, outputs, result, settled, connectionError, fatalError } = snapshot;

  const [tab, setTab] = useState<TabId | null>(null);
  const timeline = useMemo(() => deriveTimeline(events, run ? isTerminal(run.status) : false), [events, run]);
  const read = useMemo(() => (outputs ? readOutputs(outputs) : null), [outputs]);

  // Deep links (#review, #execution…) choose the tab; otherwise live runs open on the trace.
  useEffect(() => {
    if (tab !== null || !run) return;
    const fromHash = window.location.hash.slice(1);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTab(isTab(fromHash) ? fromHash : isActive(run.status) ? "execution" : "overview");
  }, [run, tab]);

  useEffect(() => {
    const onHash = () => {
      const fromHash = window.location.hash.slice(1);
      if (isTab(fromHash)) setTab(fromHash);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const open = (next: TabId) => {
    setTab(next);
    window.history.replaceState(null, "", `#${next}`);
    document.getElementById("run-tabs")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  if (fatalError && !run) {
    return (
      <div className="container page">
        {fatalError.kind === "not_found" ? (
          <EmptyState
            title="This run does not exist"
            actions={
              <Link className="button" href="/runs">
                Back to your history
              </Link>
            }
          >
            <p>It may have been removed, or it belongs to a different account.</p>
          </EmptyState>
        ) : (
          <ErrorState error={fatalError} what="this run" onRetry={restart} />
        )}
      </div>
    );
  }

  if (!run) {
    return (
      <div className="container page">
        {connectionError ? (
          <ErrorState error={connectionError} what="this run" />
        ) : (
          <Loading page label="Opening the run…" />
        )}
      </div>
    );
  }

  const live = isActive(run.status);
  const current = tab ?? (live ? "execution" : "overview");

  return (
    <div className="run container">
      <RunHeader run={run} onCancelled={restart} />

      <div className="run__banner">
        <RunStatusBanner run={run} result={result} timeline={timeline} onOpen={open} />
        {connectionError && !fatalError ? (
          <Notice tone="caution" role="status" title="Connection interrupted">
            <p>Still trying to reach the research engine. The run continues on the server either way.</p>
          </Notice>
        ) : null}
        {fatalError ? <ErrorState error={fatalError} what="updates for this run" onRetry={restart} /> : null}
      </div>

      <Tabs current={current} onSelect={open} live={live} hasReview={Boolean(result?.review ?? read?.review)} />

      <div
        className="run__panel"
        role="tabpanel"
        id={`panel-${current}`}
        aria-labelledby={`tab-${current}`}
        tabIndex={0}
      >
        {current === "overview" ? (
          <RunOverview run={run} result={result} timeline={timeline} outputs={read} onOpen={open} />
        ) : null}
        {current === "execution" ? (
          <Timeline timeline={timeline} live={live} subQuestions={read?.subQuestions} />
        ) : null}
        {current === "evidence" ? (
          read ? <EvidencePanel outputs={read} live={live} /> : <Loading label="Loading the evidence…" />
        ) : null}
        {current === "review" ? <ReviewPanel live={live} settled={settled} review={result?.review ?? null} /> : null}
        {current === "outputs" ? (
          outputs && read ? (
            <OutputsPanel outputs={outputs} read={read} live={live} />
          ) : (
            <Loading label="Loading agent outputs…" />
          )
        ) : null}
      </div>
    </div>
  );
}

function ReviewPanel({ live, settled, review }: { live: boolean; settled: boolean; review: FinalReview | null }) {
  if (review) return <ReviewDocument review={review} />;
  if (live) {
    return (
      <EmptyState title="The review is not written yet">
        <p>The Review Writer runs last, once the evidence is sufficient or a limit is reached. Follow progress in Execution.</p>
      </EmptyState>
    );
  }
  if (!settled) return <Loading label="Loading the result…" />;
  return (
    <EmptyState title="No review was written">
      <p>This run ended before the Review Writer finished. The Evidence and Execution tabs show what was completed.</p>
    </EmptyState>
  );
}

function Tabs({
  current,
  onSelect,
  live,
  hasReview,
}: {
  current: TabId;
  onSelect: (tab: TabId) => void;
  live: boolean;
  hasReview: boolean;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (event: KeyboardEvent, index: number) => {
    const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!delta && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const next =
      event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : (index + delta + TABS.length) % TABS.length;
    refs.current[next]?.focus();
    onSelect(TABS[next].id);
  };
  return (
    <div className="tabs" role="tablist" aria-label="Run views" id="run-tabs">
      {TABS.map((t, index) => (
        <button
          key={t.id}
          ref={(el) => {
            refs.current[index] = el;
          }}
          type="button"
          role="tab"
          id={`tab-${t.id}`}
          aria-selected={current === t.id}
          aria-controls={current === t.id ? `panel-${t.id}` : undefined}
          tabIndex={current === t.id ? 0 : -1}
          className="tabs__tab"
          onClick={() => onSelect(t.id)}
          onKeyDown={(e) => onKey(e, index)}
        >
          {t.label}
          {t.id === "execution" && live ? <span className="tabs__live" aria-label="live" /> : null}
          {t.id === "review" && hasReview ? <span className="tabs__dot" aria-label="available" /> : null}
        </button>
      ))}
    </div>
  );
}

function RunHeader({ run, onCancelled }: { run: RunDetail; onCancelled: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const live = isActive(run.status);
  const p = run.progress;

  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      await api.cancelRun(run.id);
      setConfirming(false);
    } catch (e) {
      setError(
        e instanceof ApiError && e.kind === "conflict" ? "The run had already finished." : errorMessage(e),
      );
    } finally {
      setBusy(false);
      onCancelled();
    }
  }

  return (
    <header className="run-head">
      <nav aria-label="Breadcrumb" className="run-head__crumbs small">
        <Link href="/runs" className="text-link">
          History
        </Link>
        <span aria-hidden="true"> / </span>
        <span className="mono muted">run {run.id.slice(0, 8)}</span>
      </nav>
      <h1 className="run-head__question">{run.question}</h1>
      <div className="run-head__meta">
        <StatusBadge status={run.status} />
        <span className="small muted">
          Started <time dateTime={run.created_at}>{formatDateTime(run.created_at)}</time>
        </span>
        {run.completed_at ? (
          <span className="small muted">
            Finished <time dateTime={run.completed_at}>{formatDateTime(run.completed_at)}</time>
          </span>
        ) : null}
        {run.request.year_from || run.request.year_to ? (
          <span className="small muted">
            Papers {run.request.year_from ?? "any"}–{run.request.year_to ?? "now"}
          </span>
        ) : null}
        {live && !confirming ? (
          <button type="button" className="button button--danger button--small run-head__cancel" onClick={() => setConfirming(true)}>
            Cancel run
          </button>
        ) : null}
      </div>

      <div className="budget" aria-label="Run budget">
        <Meter label="Iterations" value={p.iteration} max={p.max_iterations} />
        <Meter label="Model calls" value={p.llm_calls} max={p.max_llm_calls} />
        <Meter label="Tokens" value={p.tokens_used} max={p.max_tokens} />
      </div>

      {confirming ? (
        <Notice
          tone="negative"
          title="Cancel this run?"
          actions={
            <>
              <button type="button" className="button button--danger button--small" onClick={cancel} disabled={busy}>
                {busy ? "Cancelling…" : "Yes, cancel it"}
              </button>
              <button type="button" className="button button--ghost button--small" onClick={() => setConfirming(false)} disabled={busy}>
                Keep running
              </button>
            </>
          }
        >
          <p>The agents stop where they are. Everything recorded so far stays available.</p>
        </Notice>
      ) : null}
      {error ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
    </header>
  );
}

function Meter({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="meter">
      <div className="meter__row">
        <span className="meter__label">{label}</span>
        <span className="mono">
          {formatNumber(value)} / {formatNumber(max)}
        </span>
      </div>
      <div
        className="progress"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value}
      >
        <div className="progress__bar" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
