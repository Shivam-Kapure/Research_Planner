import type {
  AgentOutput,
  CandidatePaper,
  DocumentAnalysis,
  FinalReview,
  ReplanningRequest,
  ResearchPlan,
  SearchResults,
  SynthesisDecision,
} from "../api/types";

type Payload<N extends AgentOutput["schema_name"]> = Extract<AgentOutput, { schema_name: N }>;

export function ofSchema<N extends AgentOutput["schema_name"]>(outputs: AgentOutput[], name: N): Payload<N>[] {
  return outputs.filter((o): o is Payload<N> => o.schema_name === name);
}

export type RunOutputs = {
  plans: ResearchPlan[];
  searches: { iteration: number; results: SearchResults }[];
  analyses: { iteration: number; analysis: DocumentAnalysis }[];
  decisions: SynthesisDecision[];
  replans: ReplanningRequest[];
  review: FinalReview | null;
  papers: Map<string, CandidatePaper>;
  subQuestions: Map<string, string>;
};

/** Reads the persisted outputs (GET /api/runs/{id}/outputs) into what the views need. */
export function readOutputs(outputs: AgentOutput[]): RunOutputs {
  const plans = ofSchema(outputs, "research_plan").map((o) => o.payload);
  const searches = ofSchema(outputs, "search_results").map((o) => ({ iteration: o.iteration, results: o.payload }));
  const papers = new Map<string, CandidatePaper>();
  for (const { results } of searches) for (const p of results.selected) papers.set(p.paper_id, p);
  const subQuestions = new Map<string, string>();
  for (const plan of plans) for (const sq of plan.sub_questions) subQuestions.set(sq.id, sq.text);
  const reviews = ofSchema(outputs, "final_review");
  return {
    plans,
    searches,
    analyses: ofSchema(outputs, "document_analysis").map((o) => ({ iteration: o.iteration, analysis: o.payload })),
    decisions: ofSchema(outputs, "synthesis_decision").map((o) => o.payload),
    replans: ofSchema(outputs, "replanning_request").map((o) => o.payload),
    review: reviews.length ? reviews[reviews.length - 1].payload : null,
    papers,
    subQuestions,
  };
}

export function evidenceCount(outputs: RunOutputs): number {
  return outputs.analyses.reduce((sum, a) => sum + a.analysis.evidence.length, 0);
}
