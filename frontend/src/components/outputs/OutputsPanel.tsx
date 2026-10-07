import { EmptyState } from "@/components/ui/feedback";
import type {
  AgentOutput,
  CandidatePaper,
  DocumentAnalysis,
  ResearchPlan,
  SearchRequest,
  SearchResults,
} from "@/lib/api/types";
import { formatAuthors, formatTime, humanize, plural } from "@/lib/format";
import type { RunOutputs } from "@/lib/runs/outputs";

const TITLES: Record<AgentOutput["schema_name"], string> = {
  research_plan: "Research plan",
  search_request: "Search request",
  search_results: "Search results",
  document_analysis: "Document analysis",
  synthesis_decision: "Synthesis decision",
  replanning_request: "Replanning request",
  final_review: "Final review",
};

const AGENT_NAMES: Record<string, string> = {
  planner: "Research Planner",
  search: "Literature Search",
  analysis: "Document Analysis",
  synthesis: "Evidence Synthesis",
  writer: "Review Writer",
};

function outputTitle(output: AgentOutput, papers: Map<string, CandidatePaper>): string {
  if (output.schema_name === "document_analysis") {
    return papers.get(output.payload.paper_id)?.title ?? "Paper";
  }
  if (output.schema_name === "research_plan") return `Research plan v${output.payload.plan_version}`;
  if (output.schema_name === "synthesis_decision") return `Verdict: ${output.payload.verdict}`;
  if (output.schema_name === "replanning_request") return humanize(output.payload.kind);
  return TITLES[output.schema_name] ?? output.schema_name;
}

/** Every persisted agent output, grouped by iteration, with a readable view and the raw JSON. */
export function OutputsPanel({ outputs, read, live }: { outputs: AgentOutput[]; read: RunOutputs; live: boolean }) {
  if (!outputs.length) {
    return (
      <EmptyState title={live ? "No outputs yet" : "No outputs were stored"}>
        <p>
          {live
            ? "Each agent's structured output is saved the moment it finishes. The research plan arrives first."
            : "The run stopped before any agent finished, so nothing was stored."}
        </p>
      </EmptyState>
    );
  }
  const iterations = [...new Set(outputs.map((o) => o.iteration))].sort((a, b) => a - b);
  return (
    <div className="outputs">
      {iterations.map((iteration) => (
        <section key={iteration} className="outputs__iter" aria-labelledby={`out-iter-${iteration}`}>
          <h3 id={`out-iter-${iteration}`} className="outputs__iter-title">
            Iteration {iteration}
          </h3>
          <ul className="outputs__list">
            {outputs
              .filter((o) => o.iteration === iteration)
              .map((output) => (
                <li key={output.id}>
                  <details className="output">
                    <summary className="output__summary">
                      <span className="output__agent">{AGENT_NAMES[output.agent] ?? humanize(output.agent)}</span>
                      <span className="output__title">{outputTitle(output, read.papers)}</span>
                      <span className="output__schema mono">
                        {output.schema_name} v{output.schema_version} · {formatTime(output.created_at)}
                      </span>
                    </summary>
                    <div className="output__body">
                      <OutputView output={output} read={read} />
                      <details className="disclosure output__raw">
                        <summary>Raw contract JSON</summary>
                        <pre className="json">{JSON.stringify(output.payload, null, 2)}</pre>
                      </details>
                    </div>
                  </details>
                </li>
              ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function OutputView({ output, read }: { output: AgentOutput; read: RunOutputs }) {
  switch (output.schema_name) {
    case "research_plan":
      return <PlanView plan={output.payload} />;
    case "search_request":
      return <SearchRequestView request={output.payload} />;
    case "search_results":
      return <SearchResultsView results={output.payload} />;
    case "document_analysis":
      return <AnalysisView analysis={output.payload} paper={read.papers.get(output.payload.paper_id)} />;
    case "synthesis_decision":
      return (
        <p className="muted">
          {output.payload.rationale} The Evidence tab shows its coverage, themes and contradictions.
        </p>
      );
    case "replanning_request":
      return (
        <div className="kv">
          <p>
            <strong>{humanize(output.payload.kind)}</strong> from iteration {output.payload.iteration_from}
          </p>
          <ul className="plain-list">
            {output.payload.reasons.map((r, i) => (
              <li key={i}>
                {humanize(r.type)} · <span className="mono">{r.sub_question_id}</span> · {r.detail}
              </li>
            ))}
          </ul>
          {output.payload.scope_change ? <p>Scope change: {output.payload.scope_change}</p> : null}
        </div>
      );
    case "final_review":
      return (
        <p className="muted">
          “{output.payload.title}”, {plural(output.payload.sections.length, "section")} and{" "}
          {plural(output.payload.references.length, "reference")}. The Review tab shows it in full.
        </p>
      );
    default:
      return null;
  }
}

function PlanView({ plan }: { plan: ResearchPlan }) {
  return (
    <div className="kv">
      <p className="kv__lead">{plan.objective}</p>
      {plan.revision_reason ? <p className="small">Revised because: {plan.revision_reason}</p> : null}
      <ol className="sq-list">
        {plan.sub_questions.map((sq) => (
          <li key={sq.id}>
            <span className="mono">{sq.id}</span>
            <span className="sq-list__priority">Priority {sq.priority}</span>
            <p>{sq.text}</p>
            <p className="small muted">{sq.rationale}</p>
          </li>
        ))}
      </ol>
      <p>
        <span className="kv__key">Search strategy</span> {plan.search_strategy}
      </p>
      <div>
        <span className="kv__key">Keywords</span>
        <ul className="chips">
          {plan.keywords.map((k) => (
            <li key={k} className="chip">
              {k}
            </li>
          ))}
        </ul>
      </div>
      <p>
        <span className="kv__key">Include</span> {plan.inclusion_criteria.join("; ")}
      </p>
      {plan.exclusion_criteria.length ? (
        <p>
          <span className="kv__key">Exclude</span> {plan.exclusion_criteria.join("; ")}
        </p>
      ) : null}
      {plan.study_types.length ? (
        <p>
          <span className="kv__key">Study types</span> {plan.study_types.join(", ")}
        </p>
      ) : null}
    </div>
  );
}

function SearchRequestView({ request }: { request: SearchRequest }) {
  return (
    <ul className="plain-list">
      {request.targets.map((t, i) => (
        <li key={`${t.sub_question_id}-${i}`}>
          <span className="mono">{t.sub_question_id}</span> {t.queries.map((q) => `“${q}”`).join(", ")}
        </li>
      ))}
      {request.exclude_paper_ids.length ? (
        <li className="muted">{plural(request.exclude_paper_ids.length, "already-seen paper")} excluded</li>
      ) : null}
    </ul>
  );
}

function SearchResultsView({ results }: { results: SearchResults }) {
  return (
    <div className="kv">
      <p>
        {plural(results.selected.length, "paper")} selected from {plural(results.candidates_total, "candidate")} (
        {results.duplicates_removed} duplicates removed, {results.rejected_count} rejected in screening).
        {results.degraded_sources.length ? ` Degraded sources: ${results.degraded_sources.map(humanize).join(", ")}.` : ""}
      </p>
      <ol className="paper-list">
        {results.selected.map((paper) => (
          <li key={paper.paper_id} className="paper">
            <p className="paper__title">{paper.title}</p>
            <p className="small muted">
              {formatAuthors(paper.authors)}
              {paper.year ? ` · ${paper.year}` : ""}
              {paper.venue ? ` · ${paper.venue}` : ""}
              {paper.has_oa_pdf ? " · open-access PDF" : ""}
            </p>
            <p className="small">
              Relevance {paper.relevance_score.toFixed(2)} · {paper.reason}
            </p>
          </li>
        ))}
      </ol>
      <details className="disclosure">
        <summary>{plural(results.queries_executed.length, "source query", "source queries")}</summary>
        <ul className="plain-list small">
          {results.queries_executed.map((q, i) => (
            <li key={i}>
              {humanize(q.source)} · “{q.query}” · {plural(q.result_count, "result")}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function AnalysisView({ analysis, paper }: { analysis: DocumentAnalysis; paper?: CandidatePaper }) {
  return (
    <div className="kv">
      <p className="small muted">
        {paper ? `${formatAuthors(paper.authors)}${paper.year ? ` · ${paper.year}` : ""} · ` : ""}
        Read from {humanize(analysis.basis).toLowerCase()}
        {analysis.failure_reason ? ` (${humanize(analysis.failure_reason).toLowerCase()})` : ""} · extraction{" "}
        {analysis.extraction_status}
      </p>
      {analysis.study_type || analysis.context ? (
        <p>
          {analysis.study_type ? <span className="kv__key">{analysis.study_type}</span> : null} {analysis.context}
        </p>
      ) : null}
      {analysis.methods_summary ? <p>{analysis.methods_summary}</p> : null}
      {analysis.key_findings.length ? (
        <div>
          <span className="kv__key">Key findings</span>
          <ul className="plain-list">
            {analysis.key_findings.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {analysis.evidence.length ? (
        <div>
          <span className="kv__key">Grounded evidence</span>
          <ul className="evidence-items">
            {analysis.evidence.map((item) => (
              <li key={item.id} className="evidence-item">
                <p>
                  <span className="mono">{item.sub_question_id}</span> {item.claim}{" "}
                  <span className="small muted">
                    ({item.stance}, confidence {item.confidence.toFixed(2)})
                  </span>
                </p>
                <blockquote className="evidence-item__quote">
                  “{item.quote}”{item.location ? <span className="small muted"> — {item.location}</span> : null}
                </blockquote>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="muted small">No grounded evidence was extracted from this paper.</p>
      )}
      {analysis.ungrounded_dropped ? (
        <p className="small muted">
          {plural(analysis.ungrounded_dropped, "quote")} could not be found verbatim in the source and was dropped.
        </p>
      ) : null}
      {analysis.limitations.length ? (
        <p className="small">
          <span className="kv__key">Study limitations</span> {analysis.limitations.join("; ")}
        </p>
      ) : null}
    </div>
  );
}
