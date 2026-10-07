import Link from "next/link";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { EmptyState } from "@/components/ui/feedback";
import type { RunSummary } from "@/lib/api/types";
import { formatDateTime, plural } from "@/lib/format";
import { isActive, stopReasonText } from "@/lib/runs/status";

/** The user's runs as returned by GET /api/runs (newest first). */
export function RunList({ runs, empty }: { runs: RunSummary[]; empty?: string }) {
  if (!runs.length) {
    return (
      <EmptyState
        title="No research yet"
        actions={
          <Link href="/research" className="button">
            Ask a research question
          </Link>
        }
      >
        <p>{empty ?? "Runs you start appear here with their status, trace and review."}</p>
      </EmptyState>
    );
  }
  return (
    <ol className="run-list">
      {runs.map((run) => (
        <li key={run.id} className="run-list__item">
          <Link href={`/runs/${run.id}`} className="run-list__link">
            <span className="run-list__question">{run.question}</span>
            <span className="run-list__meta">
              <StatusBadge status={run.status} />
              <span className="small muted">
                <time dateTime={run.created_at}>{formatDateTime(run.created_at)}</time>
              </span>
              {run.iteration > 0 ? (
                <span className="small muted">{plural(run.iteration, "iteration")}</span>
              ) : null}
              {run.stop_reason && run.stop_reason !== "sufficient" ? (
                <span className="small muted">{stopReasonText(run.stop_reason)}</span>
              ) : null}
              {isActive(run.status) ? <span className="small run-list__live">Live</span> : null}
            </span>
          </Link>
        </li>
      ))}
    </ol>
  );
}
