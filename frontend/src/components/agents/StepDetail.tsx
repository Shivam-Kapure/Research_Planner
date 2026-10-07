import type { TraceEvent } from "@/lib/api/types";
import { formatDuration, formatNumber, formatTime, humanize } from "@/lib/format";
import { parseSummary, type Step } from "@/lib/trace/timeline";

// The low-level trace of one step: tool calls, model calls, validations, fallbacks and errors.
// Values are shown as recorded (the backend redacts secrets before anything is stored).

function argText(args: Record<string, unknown>, key: string): string | null {
  const value = args[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : null;
}

function ToolRow({ event }: { event: TraceEvent }) {
  const tool = event.tool!;
  if (tool.name === "literature_search") {
    return (
      <li className={`detail-row detail-row--${event.status}`}>
        <span className="detail-row__what">
          <span className="mono">{argText(tool.args, "sub_question_id")}</span> “{argText(tool.args, "query")}”
        </span>
        <span className="detail-row__result">{tool.result_summary}</span>
        <span className="detail-row__time mono">{formatDuration(tool.duration_ms)}</span>
      </li>
    );
  }
  if (tool.name === "retrieve_document") {
    const summary = parseSummary(tool.result_summary);
    return (
      <li className={`detail-row detail-row--${event.status}`}>
        <span className="detail-row__what mono break">{argText(tool.args, "paper_key")}</span>
        <span className="detail-row__result">
          {summary.mode ? humanize(summary.mode) : tool.result_summary}
          {summary.reason ? ` · ${humanize(summary.reason)}` : ""}
          {summary.pages && summary.pages !== "0" ? ` · ${summary.pages} pages` : ""}
          {summary.host ? ` · ${summary.host}` : ""}
        </span>
        <span className="detail-row__time mono">{formatDuration(tool.duration_ms)}</span>
      </li>
    );
  }
  return (
    <li className={`detail-row detail-row--${event.status}`}>
      <span className="detail-row__what">{tool.name}</span>
      <span className="detail-row__result">{tool.result_summary}</span>
      <span className="detail-row__time mono">{formatDuration(tool.duration_ms)}</span>
    </li>
  );
}

function LlmRow({ event }: { event: TraceEvent }) {
  const llm = event.llm!;
  const tokens = (llm.tokens_in ?? 0) + (llm.tokens_out ?? 0);
  return (
    <li className={`detail-row detail-row--${event.status}`}>
      <span className="detail-row__what mono break">
        {llm.provider}/{llm.model}
      </span>
      <span className="detail-row__result">
        {humanize(llm.kind)} #{llm.attempt} · {llm.outcome === "ok" ? "ok" : humanize(llm.outcome)}
        {llm.error_code ? ` (${humanize(llm.error_code)})` : ""}
        {tokens ? ` · ${formatNumber(tokens)} tokens` : ""}
      </span>
      <span className="detail-row__time mono">{formatDuration(llm.latency_ms)}</span>
    </li>
  );
}

export function StepDetail({ step }: { step: Step }) {
  const groups: { title: string; events: TraceEvent[]; row: (e: TraceEvent) => React.ReactNode }[] = [
    { title: "Tool calls", events: step.tools.filter((e) => e.tool), row: (e) => <ToolRow key={e.id} event={e} /> },
    { title: "Model calls", events: step.llmCalls.filter((e) => e.llm), row: (e) => <LlmRow key={e.id} event={e} /> },
    {
      title: "Validation",
      events: step.validations.filter((e) => e.validation),
      row: (e) => (
        <li key={e.id} className={`detail-row detail-row--${e.status}`}>
          <span className="detail-row__what mono">{e.validation!.schema_name}</span>
          <div className="detail-row__result">
            {e.validation!.passed ? "Passed" : "Did not pass"}
            {e.validation!.errors.length ? (
              <ul className="detail-row__list">
                {e.validation!.errors.map((err, i) => (
                  <li key={i} className="break">
                    {err}
                  </li>
                ))}
              </ul>
            ) : null}
            {e.validation!.override ? ` Override: ${e.validation!.override}` : ""}
          </div>
          <span className="detail-row__time mono">{formatTime(e.ts)}</span>
        </li>
      ),
    },
    {
      title: "Fallbacks",
      events: step.fallbacks,
      row: (e) => (
        <li key={e.id} className="detail-row detail-row--warning">
          <span className="detail-row__what">{e.decision?.route ?? e.message}</span>
          <span className="detail-row__result">{e.decision?.rationale}</span>
          <span className="detail-row__time mono">{formatTime(e.ts)}</span>
        </li>
      ),
    },
  ];

  return (
    <div className="step-detail">
      {groups
        .filter((g) => g.events.length)
        .map((group) => (
          <section key={group.title} className="step-detail__group">
            <h5 className="step-detail__title">
              {group.title} <span className="muted">({group.events.length})</span>
            </h5>
            <ol className="detail-rows">{group.events.map(group.row)}</ol>
          </section>
        ))}
      <section className="step-detail__group">
        <h5 className="step-detail__title">
          All events <span className="muted">({step.events.length})</span>
        </h5>
        <ol className="event-log">
          {step.events.map((e) => (
            <li key={e.id} className={`event-log__item event-log__item--${e.status}`}>
              <span className="mono">#{e.seq}</span>
              <span className="mono">{formatTime(e.ts)}</span>
              <span className="mono event-log__type">{e.event_type}</span>
              <span className="break">{e.message}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
