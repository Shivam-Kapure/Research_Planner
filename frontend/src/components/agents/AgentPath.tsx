import { NODE_SHORT, type Step } from "@/lib/trace/timeline";

const VERDICT_TONE: Record<string, string> = { sufficient: "positive", insufficient: "caution", contradictory: "negative" };

/** The route the run actually took, step by step, as recorded in the trace. */
export function AgentPath({ steps }: { steps: Step[] }) {
  if (!steps.length) return null;
  return (
    <ol className="agent-path" aria-label="Path taken by the agents">
      {steps.map((step, index) => {
        const loop = step.node === "replanning";
        return (
          <li
            key={step.id}
            className={`agent-path__step agent-path__step--${step.state}${loop ? " agent-path__step--loop" : ""}`}
          >
            {index > 0 ? (
              <span className="agent-path__arrow" aria-hidden="true">
                →
              </span>
            ) : null}
            <span className="agent-path__name">{NODE_SHORT[step.node]}</span>
            {step.verdict ? (
              <span className={`agent-path__note agent-path__note--${VERDICT_TONE[step.verdict.verdict] ?? "neutral"}`}>
                {step.verdict.verdict}
              </span>
            ) : null}
            {step.replan ? (
              <span className="agent-path__note">{step.replan.kind === "scope_revision" ? "scope revision" : "search revision"}</span>
            ) : null}
            {step.route?.route === "limit_reached" ? (
              <span className="agent-path__note agent-path__note--caution">limit reached</span>
            ) : null}
            {step.state === "active" ? <span className="agent-path__note">now</span> : null}
            {step.state === "failed" ? <span className="agent-path__note agent-path__note--negative">failed</span> : null}
          </li>
        );
      })}
    </ol>
  );
}
