import { AgentPath } from "@/components/agents/AgentPath";
import { ToneBadge } from "@/components/ui/StatusBadge";
import type { RunDetail, RunResult } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";
import { evidenceCount, type RunOutputs } from "@/lib/runs/outputs";
import { documentCounts, type Timeline } from "@/lib/trace/timeline";

const COVERAGE_TONE = { covered: "positive", weak: "caution", missing: "negative" } as const;

/** A summary computed only from this run's recorded trace and stored outputs. */
export function RunOverview({
  run,
  result,
  timeline,
  outputs,
  onOpen,
}: {
  run: RunDetail;
  result: RunResult | null;
  timeline: Timeline;
  outputs: RunOutputs | null;
  onOpen: (tab: "review" | "execution") => void;
}) {
  const docs = documentCounts(timeline.steps);
  const selected = outputs?.searches.reduce((n, s) => n + s.results.selected.length, 0) ?? 0;
  const plan = outputs?.plans.at(-1) ?? null;
  const decision = outputs?.decisions.at(-1) ?? null;
  const coverage = new Map(decision?.coverage.map((c) => [c.sub_question_id, c.status]) ?? []);
  const review = result?.review ?? outputs?.review ?? null;

  return (
    <div className="overview">
      <section aria-labelledby="ov-path">
        <div className="overview__head">
          <h3 id="ov-path" className="overview__h">
            The path the agents took
          </h3>
          <button type="button" className="link-button small" onClick={() => onOpen("execution")}>
            Open the full trace
          </button>
        </div>
        {timeline.steps.length ? (
          <AgentPath steps={timeline.steps} />
        ) : (
          <p className="muted">No agent has started yet.</p>
        )}
      </section>

      <section aria-label="Run figures">
        <dl className="facts">
          <div>
            <dt>Iterations</dt>
            <dd>
              {run.progress.iteration} <small>of {run.progress.max_iterations}</small>
            </dd>
          </div>
          <div>
            <dt>Papers selected</dt>
            <dd>{selected}</dd>
          </div>
          <div>
            <dt>Documents read</dt>
            <dd>
              {docs.fullText + docs.abstractOnly}{" "}
              <small>
                {docs.fullText} full text · {docs.abstractOnly} abstract
              </small>
            </dd>
          </div>
          <div>
            <dt>Evidence items</dt>
            <dd>{outputs ? evidenceCount(outputs) : 0}</dd>
          </div>
          <div>
            <dt>Model calls</dt>
            <dd>
              {run.progress.llm_calls} <small>of {run.progress.max_llm_calls}</small>
            </dd>
          </div>
          <div>
            <dt>Tokens</dt>
            <dd>{formatNumber(run.progress.tokens_used)}</dd>
          </div>
        </dl>
      </section>

      {plan ? (
        <section aria-labelledby="ov-plan" className="overview__plan">
          <h3 id="ov-plan" className="overview__h">
            Research plan{plan.plan_version > 1 ? ` (version ${plan.plan_version})` : ""}
          </h3>
          <p className="overview__objective">{plan.objective}</p>
          <ol className="sq-overview">
            {plan.sub_questions.map((sq) => {
              const status = coverage.get(sq.id);
              return (
                <li key={sq.id}>
                  <span className="mono">{sq.id}</span>
                  <p>{sq.text}</p>
                  <span className="sq-overview__meta">
                    <span className="small muted">Priority {sq.priority}</span>
                    {status ? <ToneBadge tone={COVERAGE_TONE[status]}>{status}</ToneBadge> : null}
                  </span>
                </li>
              );
            })}
          </ol>
          {decision ? (
            <p className="small muted">Coverage as judged by the latest synthesis (iteration {decision.iteration}).</p>
          ) : null}
        </section>
      ) : null}

      {review ? (
        <section className="overview__review">
          <p className="eyebrow">The result</p>
          <p className="overview__review-title">{review.title}</p>
          <button type="button" className="button" onClick={() => onOpen("review")}>
            Read the review
          </button>
        </section>
      ) : null}
    </div>
  );
}
