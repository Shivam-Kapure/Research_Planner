import { ToneBadge } from "@/components/ui/StatusBadge";
import { EmptyState } from "@/components/ui/feedback";
import type { EvidenceItem, ReplanningRequest, SynthesisDecision } from "@/lib/api/types";
import { humanize, plural } from "@/lib/format";
import type { RunOutputs } from "@/lib/runs/outputs";
import type { Tone } from "@/lib/runs/status";

const VERDICT: Record<SynthesisDecision["verdict"], { tone: Tone; label: string }> = {
  sufficient: { tone: "positive", label: "Sufficient" },
  insufficient: { tone: "caution", label: "Insufficient" },
  contradictory: { tone: "negative", label: "Contradictory" },
};

const COVERAGE: Record<string, { tone: Tone; label: string }> = {
  covered: { tone: "positive", label: "Covered" },
  weak: { tone: "caution", label: "Weak" },
  missing: { tone: "negative", label: "Missing" },
};

/** Each Evidence Synthesis decision and the replanning it triggered, from the stored outputs. */
export function EvidencePanel({ outputs, live }: { outputs: RunOutputs; live: boolean }) {
  if (!outputs.decisions.length) {
    return (
      <EmptyState title={live ? "No synthesis yet" : "No evidence was synthesised"}>
        <p>
          {live
            ? "Evidence Synthesis runs after the papers of the first iteration are analysed. Its verdict will appear here."
            : "The run stopped before Evidence Synthesis produced a decision. The Execution tab shows where it stopped."}
        </p>
      </EmptyState>
    );
  }

  const evidence = new Map<string, EvidenceItem>();
  for (const { analysis } of outputs.analyses) for (const item of analysis.evidence) evidence.set(item.id, item);

  return (
    <div className="evidence">
      {outputs.decisions.map((decision) => {
        const replan = outputs.replans.find((r) => r.iteration_from === decision.iteration);
        return (
          <section key={decision.iteration} className="decision" aria-labelledby={`decision-${decision.iteration}`}>
            <header className="decision__head">
              <h3 id={`decision-${decision.iteration}`} className="decision__title">
                Iteration {decision.iteration}
              </h3>
              <ToneBadge tone={VERDICT[decision.verdict].tone}>Evidence {VERDICT[decision.verdict].label.toLowerCase()}</ToneBadge>
            </header>
            <p className="decision__rationale">{decision.rationale}</p>
            {decision.validator_override ? (
              <p className="decision__override small">
                The deterministic validator overrode the model&apos;s verdict of{" "}
                <strong>{decision.validator_override.original_verdict}</strong>: {decision.validator_override.rule_failed}.
              </p>
            ) : null}

            <div className="coverage">
              <h4 className="decision__label">Coverage by sub-question</h4>
              <ul className="coverage__list">
                {decision.coverage.map((c) => (
                  <li key={c.sub_question_id} className="coverage__item">
                    <span className="mono coverage__id">{c.sub_question_id}</span>
                    <span className="coverage__text">{outputs.subQuestions.get(c.sub_question_id) ?? "Sub-question"}</span>
                    <span className="coverage__counts small muted">
                      {plural(c.supporting_papers, "paper")}, {c.full_text_papers} full text
                    </span>
                    <ToneBadge tone={COVERAGE[c.status]?.tone ?? "neutral"}>{COVERAGE[c.status]?.label ?? c.status}</ToneBadge>
                  </li>
                ))}
              </ul>
            </div>

            {decision.themes.length ? (
              <div>
                <h4 className="decision__label">Themes</h4>
                <ul className="themes">
                  {decision.themes.map((theme, i) => (
                    <li key={i}>
                      <p className="themes__title">{theme.title}</p>
                      <p className="muted">{theme.summary}</p>
                      <p className="small muted">{plural(theme.evidence_ids.length, "evidence item")}</p>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {decision.contradictions.length ? (
              <div>
                <h4 className="decision__label">Contradictions</h4>
                <ul className="contradictions">
                  {decision.contradictions.map((c, i) => (
                    <li key={i} className="contradictions__item">
                      <p>
                        <span className="mono">{c.sub_question_id}</span> {c.explanation}
                      </p>
                      <ClaimPair a={evidence.get(c.claim_a)} b={evidence.get(c.claim_b)} />
                      <p className="small muted">
                        {c.resolved ? `Resolved by ${c.moderator ?? "a moderator"}.` : "Unresolved."}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {replan ? <ReplanSummary replan={replan} subQuestions={outputs.subQuestions} /> : null}
          </section>
        );
      })}
    </div>
  );
}

function ClaimPair({ a, b }: { a?: EvidenceItem; b?: EvidenceItem }) {
  if (!a && !b) return null;
  return (
    <div className="claim-pair">
      {[a, b].map((item, i) =>
        item ? (
          <blockquote key={i} className="claim">
            <p>{item.claim}</p>
            <footer className="small muted">{humanize(item.stance)}</footer>
          </blockquote>
        ) : null,
      )}
    </div>
  );
}

function ReplanSummary({ replan, subQuestions }: { replan: ReplanningRequest; subQuestions: Map<string, string> }) {
  return (
    <div className="replan">
      <h4 className="decision__label">
        Replanning: {replan.kind === "scope_revision" ? "scope revision → Research Planner" : "search revision → Literature Search"}
      </h4>
      <ul className="replan__reasons">
        {replan.reasons.map((r, i) => (
          <li key={i}>
            <strong>{humanize(r.type)}</strong> <span className="mono">{r.sub_question_id}</span> {r.detail}
            {subQuestions.get(r.sub_question_id) ? (
              <span className="small muted"> — {subQuestions.get(r.sub_question_id)}</span>
            ) : null}
          </li>
        ))}
      </ul>
      {replan.scope_change ? <p className="replan__scope">Scope change: {replan.scope_change}</p> : null}
      {replan.directives.length ? (
        <div>
          <p className="small muted">New search directions</p>
          <ul className="chips">
            {replan.directives.flatMap((d) =>
              d.suggested_queries.map((q) => (
                <li key={`${d.sub_question_id}-${q}`} className="chip">
                  {q}
                </li>
              )),
            )}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
