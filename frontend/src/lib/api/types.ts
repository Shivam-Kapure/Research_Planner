// Mirrors of the backend's Pydantic response models. Sources of truth:
// backend/app/schemas/api/{auth,credentials,runs}.py, backend/app/schemas/trace.py and
// backend/app/schemas/contracts/*.py. Timestamps are ISO 8601 strings, UUIDs are strings.

export type User = { id: string; email: string; created_at: string };

export type Provider = "groq" | "gemini";

export type CredentialStatus = {
  provider: Provider;
  configured: boolean;
  key_hint: string | null;
  status: "unverified" | "valid" | "invalid" | null;
  validated_at: string | null;
  updated_at: string | null;
};

export const RUN_STATUSES = [
  "queued",
  "running",
  "completed",
  "completed_with_limitations",
  "partial",
  "failed",
  "cancelled",
] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

export type StopReason = "sufficient" | "iteration_limit" | "budget_limit";

export type ResearchRequest = {
  question: string;
  max_iterations: number;
  year_from: number | null;
  year_to: number | null;
};

export type RunError = { code: string; message: string; node: string | null };

export type RunProgress = {
  iteration: number;
  max_iterations: number;
  llm_calls: number;
  max_llm_calls: number;
  tokens_used: number;
  max_tokens: number;
};

export type RunSummary = {
  id: string;
  question: string;
  status: RunStatus;
  iteration: number;
  stop_reason: StopReason | string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type RunDetail = RunSummary & {
  request: ResearchRequest;
  started_at: string | null;
  error: RunError | null;
  progress: RunProgress;
};

export type RunPage = { items: RunSummary[]; total: number; limit: number; offset: number };

// ---- Trace (backend/app/schemas/trace.py) ----

export type TraceAgent = "planner" | "search" | "analysis" | "synthesis" | "writer" | "orchestrator";

export type ToolInfo = {
  name: string;
  args: Record<string, unknown>;
  result_summary: string | null;
  duration_ms: number | null;
};
export type DecisionInfo = {
  route: string;
  rationale: string;
  from_agent: TraceAgent | null;
  to_agent: TraceAgent | null;
};
export type ValidationInfo = {
  schema_name: string;
  passed: boolean;
  errors: string[];
  dropped_items: number;
  override: string | null;
  raw_excerpt: string | null;
};
export type LLMInfo = {
  provider: "groq" | "gemini";
  model: string;
  attempt: number;
  kind: "initial" | "transient_retry" | "repair";
  outcome: "ok" | "error" | "invalid_output";
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number | null;
  error_code: string | null;
};
export type ErrorInfo = { code: string; message: string; retryable: boolean; attempt: number | null };

export type TraceEvent = {
  id: string;
  run_id: string;
  seq: number;
  ts: string;
  iteration: number;
  agent: TraceAgent | string;
  event_type: string;
  status: "ok" | "warning" | "failed" | string;
  message: string;
  parent_id: string | null;
  input_ref: string | null;
  output_ref: string | null;
  tool: ToolInfo | null;
  decision: DecisionInfo | null;
  validation: ValidationInfo | null;
  llm: LLMInfo | null;
  error: ErrorInfo | null;
};

// ---- Contracts (backend/app/schemas/contracts) ----

export type YearRange = { start: number; end: number };
export type SearchFilters = { year_range: YearRange | null; study_types: string[] };

export type SubQuestion = { id: string; text: string; rationale: string; priority: number };

export type ResearchPlan = {
  schema_version: number;
  plan_version: number;
  objective: string;
  sub_questions: SubQuestion[];
  search_strategy: string;
  inclusion_criteria: string[];
  exclusion_criteria: string[];
  keywords: string[];
  year_range: YearRange | null;
  study_types: string[];
  revision_reason: string | null;
};

export type SearchRequest = {
  schema_version: number;
  iteration: number;
  targets: { sub_question_id: string; queries: string[]; filters: SearchFilters }[];
  exclude_paper_ids: string[];
  k: number;
};

export type CandidatePaper = {
  paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  doi: string | null;
  sub_question_ids: string[];
  relevance_score: number;
  reason: string;
  has_oa_pdf: boolean;
};

export type SearchResults = {
  schema_version: number;
  iteration: number;
  queries_executed: {
    source: "openalex" | "semantic_scholar";
    query: string;
    filters: SearchFilters;
    result_count: number;
  }[];
  candidates_total: number;
  duplicates_removed: number;
  degraded_sources: string[];
  selected: CandidatePaper[];
  rejected_count: number;
};

export type EvidenceItem = {
  id: string;
  paper_id: string;
  sub_question_id: string;
  claim: string;
  stance: "supports" | "refutes" | "mixed" | "neutral";
  quote: string;
  location: string | null;
  confidence: number;
};

export type DocumentAnalysis = {
  schema_version: number;
  paper_id: string;
  basis: "full_text" | "abstract_only" | "metadata_only";
  extraction_status: "succeeded" | "degraded" | "failed";
  failure_reason: string | null;
  study_type: string | null;
  context: string | null;
  methods_summary: string | null;
  key_findings: string[];
  limitations: string[];
  evidence: EvidenceItem[];
  ungrounded_dropped: number;
};

export type Verdict = "sufficient" | "insufficient" | "contradictory";

export type Coverage = {
  sub_question_id: string;
  supporting_papers: number;
  full_text_papers: number;
  status: "covered" | "weak" | "missing";
};

export type Contradiction = {
  sub_question_id: string;
  claim_a: string;
  claim_b: string;
  explanation: string;
  resolved: boolean;
  moderator: string | null;
};

export type SynthesisDecision = {
  schema_version: number;
  iteration: number;
  verdict: Verdict;
  coverage: Coverage[];
  contradictions: Contradiction[];
  themes: { title: string; summary: string; evidence_ids: string[] }[];
  rationale: string;
  validator_override: { original_verdict: Verdict; rule_failed: string } | null;
};

export type ReplanningRequest = {
  schema_version: number;
  iteration_from: number;
  kind: "search_revision" | "scope_revision";
  reasons: { type: "gap" | "contradiction" | "low_quality"; sub_question_id: string; detail: string }[];
  directives: { sub_question_id: string; suggested_queries: string[]; filters: SearchFilters }[];
  scope_change: string | null;
  exclude_paper_ids: string[];
};

export type ReviewSection = {
  heading: string;
  kind: "introduction" | "body" | "conclusion";
  body_markdown: string;
  citation_keys: string[];
  evidence_ids: string[];
};

export type Reference = {
  citation_key: string;
  paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  doi: string | null;
};

export type FinalReview = {
  schema_version: number;
  title: string;
  abstract: string;
  sections: ReviewSection[];
  limitations: string[];
  evidence_status: "sufficient" | "limited" | "contradictory";
  references: Reference[];
};

export type RunResult = {
  run_id: string;
  status: RunStatus;
  stop_reason: StopReason | string | null;
  review: FinalReview | null;
  synthesis: SynthesisDecision | null;
  error: RunError | null;
};

type OutputBase<N extends string, P> = {
  id: string;
  agent: string;
  iteration: number;
  schema_name: N;
  schema_version: number;
  created_at: string;
  payload: P;
};

/** GET /api/runs/{id}/outputs items, discriminated by schema_name. */
export type AgentOutput =
  | OutputBase<"research_plan", ResearchPlan>
  | OutputBase<"search_request", SearchRequest>
  | OutputBase<"search_results", SearchResults>
  | OutputBase<"document_analysis", DocumentAnalysis>
  | OutputBase<"synthesis_decision", SynthesisDecision>
  | OutputBase<"replanning_request", ReplanningRequest>
  | OutputBase<"final_review", FinalReview>;
