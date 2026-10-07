import type { RunDetail, RunResult } from "@/lib/api/types";
import { humanize } from "@/lib/format";
import { STATUS_META, errorHint, stopReasonText } from "@/lib/runs/status";
import { NODE_LABEL, type Timeline } from "@/lib/trace/timeline";
import { EVIDENCE_STATUS } from "@/components/results/ReviewDocument";
import { Notice } from "@/components/ui/feedback";

/** The run's outcome and confidence, stated at the top of the page in plain language. */
export function RunStatusBanner({
  run,
  result,
  timeline,
  onOpen,
}: {
  run: RunDetail;
  result: RunResult | null;
  timeline: Timeline;
  onOpen: (tab: "review" | "evidence" | "execution") => void;
}) {
  const meta = STATUS_META[run.status];
  const review = result?.review ?? null;
  const reviewLink = review ? (
    <button type="button" className="button button--small" onClick={() => onOpen("review")}>
      Read the review
    </button>
  ) : null;

  switch (run.status) {
    case "queued":
      return (
        <Notice tone="neutral" role="status" title="Queued">
          <p>{meta.description}</p>
        </Notice>
      );
    case "running": {
      const step = timeline.current;
      return (
        <Notice
          tone="active"
          role="status"
          title={step ? `${NODE_LABEL[step.node]} is working` : "Research in progress"}
        >
          <p>
            Iteration {Math.max(1, run.progress.iteration)} of at most {run.progress.max_iterations}. {meta.description}
          </p>
        </Notice>
      );
    }
    case "completed": {
      const status = review ? EVIDENCE_STATUS[review.evidence_status] : null;
      return (
        <Notice tone="positive" title={status ? `${status.label}. The review is ready.` : "Completed"} actions={reviewLink}>
          <p>{status?.meaning ?? meta.description}</p>
        </Notice>
      );
    }
    case "completed_with_limitations": {
      const status = review ? EVIDENCE_STATUS[review.evidence_status] : null;
      const limits = review?.limitations ?? [];
      return (
        <Notice
          tone="caution"
          title={`Review written with limitations${status ? ` · ${status.label}` : ""}`}
          actions={
            <>
              {reviewLink}
              <button type="button" className="button button--ghost button--small" onClick={() => onOpen("evidence")}>
                See the evidence
              </button>
            </>
          }
        >
          <p>{stopReasonText(run.stop_reason) ?? meta.description}</p>
          {limits.length ? (
            <ul className="banner-list">
              {limits.slice(0, 3).map((item, i) => (
                <li key={i}>{item}</li>
              ))}
              {limits.length > 3 ? <li className="muted">and {limits.length - 3} more in the review.</li> : null}
            </ul>
          ) : null}
        </Notice>
      );
    }
    case "partial":
      return (
        <Notice
          tone="caution"
          title="No final review: a later step failed"
          actions={
            <button type="button" className="button button--small" onClick={() => onOpen("evidence")}>
              See the last synthesis
            </button>
          }
        >
          <p>
            {meta.description}
            {result?.synthesis ? ` The last verdict was “${result.synthesis.verdict}”.` : ""}
          </p>
          {run.error ? <ErrorLine run={run} /> : null}
        </Notice>
      );
    case "failed":
      return (
        <Notice
          tone="negative"
          role="alert"
          title={run.error?.node && run.error.node !== "run" ? `Failed during ${humanize(run.error.node).toLowerCase()}` : "The run failed"}
          actions={
            <button type="button" className="button button--ghost button--small" onClick={() => onOpen("execution")}>
              Inspect the trace
            </button>
          }
        >
          {run.error ? <ErrorLine run={run} /> : <p>{meta.description}</p>}
        </Notice>
      );
    case "cancelled":
      return (
        <Notice tone="neutral" title="Cancelled">
          <p>{meta.description}</p>
        </Notice>
      );
  }
}

function ErrorLine({ run }: { run: RunDetail }) {
  const hint = errorHint(run.error);
  return (
    <>
      <p>{run.error?.message}</p>
      {hint && hint !== run.error?.message ? <p>{hint}</p> : null}
    </>
  );
}
