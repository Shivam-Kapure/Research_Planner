import type { RunError, RunStatus } from "../api/types";

export const TERMINAL: readonly RunStatus[] = [
  "completed",
  "completed_with_limitations",
  "partial",
  "failed",
  "cancelled",
];

export const isTerminal = (status: RunStatus) => TERMINAL.includes(status);
export const isActive = (status: RunStatus) => status === "queued" || status === "running";

export type Tone = "neutral" | "active" | "positive" | "caution" | "negative";

/** Labels and descriptions follow backend/app/schemas/api/runs.py and docs/PHASE7_RUNS_API.md. */
export const STATUS_META: Record<RunStatus, { label: string; tone: Tone; description: string }> = {
  queued: {
    label: "Queued",
    tone: "neutral",
    description: "Waiting for a free research slot. It starts automatically.",
  },
  running: {
    label: "Running",
    tone: "active",
    description: "The agents are working. The trace below updates as each step is recorded.",
  },
  completed: {
    label: "Completed",
    tone: "positive",
    description: "The evidence was judged sufficient and the review was written.",
  },
  completed_with_limitations: {
    label: "Completed with limitations",
    tone: "caution",
    description:
      "A review was written, but research stopped at a limit before the evidence was judged sufficient.",
  },
  partial: {
    label: "Partial",
    tone: "caution",
    description:
      "Evidence was synthesised, but a later step failed, so no final review was written.",
  },
  failed: {
    label: "Failed",
    tone: "negative",
    description: "The run stopped because of an error.",
  },
  cancelled: {
    label: "Cancelled",
    tone: "neutral",
    description: "The run was cancelled. Everything recorded before that is kept.",
  },
};

export const STOP_REASON_TEXT: Record<string, string> = {
  sufficient: "Stopped because the evidence was judged sufficient.",
  iteration_limit: "Stopped at the iteration limit before the evidence was judged sufficient.",
  budget_limit:
    "Stopped because the LLM call budget could not cover another research iteration.",
};

export function stopReasonText(reason: string | null): string | null {
  if (!reason) return null;
  return STOP_REASON_TEXT[reason] ?? `Stopped: ${reason.replaceAll("_", " ")}.`;
}

/** Plain-language guidance for the backend's safe error codes (RunError.code). */
const ERROR_HINTS: Record<string, string> = {
  no_provider_configured:
    "No language model is available. Add a Groq or Gemini key in Settings and try again.",
  auth_failed: "A provider rejected your API key. Replace it in Settings.",
  rate_limited: "A provider's free-tier rate limit was reached. Wait a few minutes and retry.",
  daily_quota_exhausted: "A provider's free daily quota is used up. Try again tomorrow or add another provider.",
  provider_unavailable: "The language model provider was unavailable. Try again later.",
  structured_output_invalid:
    "The language model kept returning output that failed validation, so the step was stopped.",
  budget_exhausted: "The run used up its LLM call or token budget.",
  literature_unavailable: "The literature sources could not be reached. Try again later.",
  interrupted: "The server restarted while this run was in progress, so it could not finish.",
  timeout: "The run reached its time limit.",
  cancelled: "The run was cancelled.",
  internal_error: "An unexpected error occurred in the research engine.",
};

export function errorHint(error: RunError | null): string | null {
  if (!error) return null;
  return ERROR_HINTS[error.code] ?? null;
}
