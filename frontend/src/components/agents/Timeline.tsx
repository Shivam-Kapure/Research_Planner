import type { TraceEvent } from "@/lib/api/types";
import { formatDuration, formatNumber, formatTime, humanize, plural } from "@/lib/format";
import { stopReasonText } from "@/lib/runs/status";
import {
  NODE_LABEL,
  describeEvent,
  documentCounts,
  durationMs,
  failedLlmCalls,
  searchCalls,
  type Step,
  type Timeline as TimelineModel,
} from "@/lib/trace/timeline";
import { EmptyState } from "@/components/ui/feedback";
import { StepDetail } from "./StepDetail";

const VERDICT_TONE: Record<string, string> = {
  sufficient: "positive",
  insufficient: "caution",
  contradictory: "negative",
};

const STATE_LABEL: Record<Step["state"], string> = {
  active: "In progress",
  completed: "Done",
  failed: "Failed",
  stopped: "Stopped",
};

/** "low_quality sq-1: weak: 1 paper(s), 0 full text" → parts for display. */
function parseReason(reason: string) {
  const match = /^([a-z_]+)\s+(sq-\d+):\s*(.*)$/.exec(reason);
  if (!match) return { type: null, subQuestion: null, detail: reason };
  return { type: humanize(match[1]), subQuestion: match[2], detail: match[3] };
}

function stepFacts(step: Step): string[] {
  const facts: string[] = [];
  const searches = searchCalls(step);
  if (searches.length) facts.push(plural(searches.length, "literature search", "literature searches"));
  if (step.node === "document_analysis") {
    const docs = documentCounts([step]);
    const total = docs.fullText + docs.abstractOnly + docs.unavailable;
    if (total) {
      const parts = [`${docs.fullText} full text`, `${docs.abstractOnly} abstract only`];
      if (docs.unavailable) parts.push(`${docs.unavailable} unavailable`);
      facts.push(`${plural(total, "document")} (${parts.join(", ")})`);
    }
  }
  if (step.llmCalls.length) {
    const failed = failedLlmCalls(step).length;
    facts.push(
      `${plural(step.llmCalls.length, "model call")}${failed ? ` (${failed} retried or failed)` : ""}`,
    );
  }
  if (step.fallbacks.length) facts.push(plural(step.fallbacks.length, "provider fallback"));
  const dropped = step.validations.reduce((n, v) => n + (v.validation?.dropped_items ?? 0), 0);
  if (dropped) facts.push(`${plural(dropped, "ungrounded quote")} dropped`);
  if (step.tokens) facts.push(`${formatNumber(step.tokens)} tokens`);
  return facts;
}

function latestActivity(step: Step): TraceEvent | null {
  return step.events.length ? step.events[step.events.length - 1] : null;
}

export function Timeline({
  timeline,
  live,
  subQuestions,
}: {
  timeline: TimelineModel;
  live: boolean;
  subQuestions?: Map<string, string>;
}) {
  if (!timeline.steps.length && !timeline.runStarted) {
    return (
      <EmptyState title={live ? "Waiting for the first agent" : "No trace was recorded"}>
        <p>
          {live
            ? "The run is queued. The Research Planner's first step will appear here as soon as it starts."
            : "This run ended before any agent started, so there is nothing to show."}
        </p>
      </EmptyState>
    );
  }

  return (
    <div className="timeline">
      {timeline.runStarted ? (
        <p className="tl-edge">
          <span className="mono">{formatTime(timeline.runStarted.ts)}</span>
          <span>{humanize(timeline.runStarted.message)}</span>
        </p>
      ) : null}

      {timeline.iterations.map((group, index) => (
        <section key={`${group.iteration}-${index}`} className="tl-iter" aria-labelledby={`iter-${index}`}>
          <h3 id={`iter-${index}`} className="tl-iter__head">
            <span className="tl-iter__label">Iteration</span>
            <span className="tl-iter__num">{group.iteration}</span>
          </h3>
          <ol className="tl-steps">
            {group.steps.map((step) => (
              <TimelineStep key={step.id} step={step} live={live} subQuestions={subQuestions} />
            ))}
          </ol>
        </section>
      ))}

      {timeline.runEvents.length ? (
        <div className="tl-run-events">
          {timeline.runEvents.map((event) => (
            <p key={event.id} className={`tl-edge tl-edge--${event.status}`}>
              <span className="mono">{formatTime(event.ts)}</span>
              <span>{event.error ? `${event.error.code}: ${event.error.message}` : event.message}</span>
            </p>
          ))}
        </div>
      ) : null}

      {timeline.runCompleted ? (
        <p className="tl-edge tl-edge--end">
          <span className="mono">{formatTime(timeline.runCompleted.ts)}</span>
          <span>{humanize(timeline.runCompleted.message.replace(/, stop_reason=[a-z_]+/, ""))}</span>
        </p>
      ) : live ? (
        <p className="tl-edge tl-edge--live" role="status">
          <span className="pulse" aria-hidden="true" />
          <span>Recording… new steps appear as the agents work.</span>
        </p>
      ) : null}
    </div>
  );
}

function TimelineStep({
  step,
  live,
  subQuestions,
}: {
  step: Step;
  live: boolean;
  subQuestions?: Map<string, string>;
}) {
  const facts = stepFacts(step);
  const latest = step.state === "active" ? latestActivity(step) : null;
  const duration = durationMs(step);
  return (
    <li className={`tl-step tl-step--${step.state}`} data-node={step.node} aria-current={step.state === "active" && live ? "step" : undefined}>
      <span className="tl-step__marker" aria-hidden="true" />
      <div className="tl-step__body">
        <div className="tl-step__head">
          <h4 className="tl-step__name">{NODE_LABEL[step.node]}</h4>
          <span className={`tl-step__state tl-step__state--${step.state}`}>{STATE_LABEL[step.state]}</span>
          <span className="tl-step__time mono">
            {formatTime(step.startedAt)}
            {duration !== null ? ` · ${formatDuration(duration)}` : ""}
          </span>
        </div>

        {step.summary ? <p className="tl-step__summary">{humanize(step.summary)}</p> : null}
        {latest ? (
          <p className="tl-step__summary tl-step__summary--live">
            <span className="pulse" aria-hidden="true" /> <span className="break">{describeEvent(latest)}</span>
          </p>
        ) : null}
        {step.state === "active" && !latest ? (
          <p className="tl-step__summary tl-step__summary--live">
            <span className="pulse" aria-hidden="true" /> Starting…
          </p>
        ) : null}

        {facts.length ? (
          <ul className="tl-step__facts">
            {facts.map((fact) => (
              <li key={fact}>{fact}</li>
            ))}
          </ul>
        ) : null}

        {step.verdict ? (
          <div className={`tl-callout tone-${VERDICT_TONE[step.verdict.verdict] ?? "neutral"}`}>
            <p className="tl-callout__title">
              <span className="tl-callout__kicker">Verdict</span> Evidence {step.verdict.verdict}
            </p>
            <p className="tl-callout__body">{step.verdict.rationale}</p>
            {step.overrides.length ? (
              <p className="tl-callout__note">Validator override: {step.overrides.join("; ")}</p>
            ) : null}
          </div>
        ) : null}

        {step.route ? <RouteNote route={step.route} /> : null}

        {step.replan ? (
          <div className="tl-callout tl-callout--replan tone-active">
            <p className="tl-callout__title">
              <span className="tl-callout__kicker">Adaptive replanning</span>
              {step.replan.kind === "scope_revision" ? "Scope revision" : "Search revision"}
              {step.replan.toNode ? ` → back to ${NODE_LABEL[step.replan.toNode]}` : ""}
              {` · iteration ${step.replan.nextIteration}`}
            </p>
            <ul className="tl-reasons">
              {step.replan.reasons.map((reason, i) => {
                const parsed = parseReason(reason);
                const text = parsed.subQuestion ? subQuestions?.get(parsed.subQuestion) : undefined;
                return (
                  <li key={i}>
                    {parsed.type ? <span className="tl-reasons__type">{parsed.type}</span> : null}
                    {parsed.subQuestion ? <span className="mono">{parsed.subQuestion}</span> : null}
                    <span>{parsed.detail}</span>
                    {text ? <span className="tl-reasons__sq">{text}</span> : null}
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}

        {step.errors.length ? (
          <ul className="tl-errors">
            {step.errors.map((event) => (
              <li key={event.id} className={`tl-errors__item tl-errors__item--${event.status}`}>
                <span className="mono">{event.error?.code ?? "error"}</span> {event.error?.message ?? event.message}
              </li>
            ))}
          </ul>
        ) : null}

        {step.events.length ? (
          <details className="disclosure tl-step__detail">
            <summary>Trace detail · {plural(step.events.length, "event")}</summary>
            <StepDetail step={step} />
          </details>
        ) : null}
      </div>
    </li>
  );
}

function RouteNote({ route }: { route: NonNullable<Step["route"]> }) {
  if (route.route === "limit_reached") {
    return (
      <div className="tl-callout tone-caution">
        <p className="tl-callout__title">
          <span className="tl-callout__kicker">Limit reached</span>
          {stopReasonText(route.stopReason) ?? "Research stopped at a limit."}
        </p>
        <p className="tl-callout__body">The orchestrator sent the run to the Review Writer, which states the limitation.</p>
      </div>
    );
  }
  const target = route.route === "replanning" ? "Replanning" : route.route === "writer" ? "Review Writer" : humanize(route.route);
  return (
    <p className="tl-route">
      <span className="tl-route__arrow" aria-hidden="true">
        ↳
      </span>
      Orchestrator routed the run to <strong>{target}</strong>
      <span className="muted"> · {route.rationale.replace(/, stop_reason=[a-z_]+/, "")}</span>
    </p>
  );
}
