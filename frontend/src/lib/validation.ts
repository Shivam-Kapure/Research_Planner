// Client-side checks that mirror the backend's request models, so users see problems before
// submitting. The backend still validates everything (422s are shown the same way).

export type Errors<K extends string> = Partial<Record<K, string>>;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** backend/app/schemas/api/auth.py: RegisterRequest (password 10–128) and LoginRequest. */
export function validateCredentials(
  email: string,
  password: string,
  mode: "login" | "register",
): Errors<"email" | "password"> {
  const errors: Errors<"email" | "password"> = {};
  const trimmed = email.trim();
  if (!trimmed) errors.email = "Enter your email address.";
  else if (!EMAIL.test(trimmed) || trimmed.length > 254) errors.email = "Enter a valid email address.";
  if (!password) errors.password = "Enter your password.";
  else if (password.length > 128) errors.password = "Passwords can be at most 128 characters.";
  else if (mode === "register" && password.length < 10) {
    errors.password = "Use at least 10 characters.";
  }
  return errors;
}

export const QUESTION_MIN = 15;
export const QUESTION_MAX = 1000;
export const YEAR_MIN = 1900;
export const YEAR_MAX = 2100;

export type ResearchForm = {
  question: string;
  maxIterations: number;
  yearFrom: string;
  yearTo: string;
};

/** backend/app/schemas/contracts/planning.py: ResearchRequest. */
export function validateResearch(form: ResearchForm): Errors<"question" | "yearFrom" | "yearTo"> {
  const errors: Errors<"question" | "yearFrom" | "yearTo"> = {};
  const question = form.question.trim();
  if (question.length < QUESTION_MIN) {
    errors.question = `Write at least ${QUESTION_MIN} characters so the planner has something to work with.`;
  } else if (question.length > QUESTION_MAX) {
    errors.question = `Keep the question under ${QUESTION_MAX} characters.`;
  }
  const from = parseYear(form.yearFrom);
  const to = parseYear(form.yearTo);
  if (from === "invalid") errors.yearFrom = `Use a year between ${YEAR_MIN} and ${YEAR_MAX}.`;
  if (to === "invalid") errors.yearTo = `Use a year between ${YEAR_MIN} and ${YEAR_MAX}.`;
  if (typeof from === "number" && typeof to === "number" && from > to) {
    errors.yearTo = "The end year must not be before the start year.";
  }
  return errors;
}

function parseYear(value: string): number | null | "invalid" {
  const text = value.trim();
  if (!text) return null;
  if (!/^\d{4}$/.test(text)) return "invalid";
  const year = Number(text);
  return year >= YEAR_MIN && year <= YEAR_MAX ? year : "invalid";
}

export function toResearchRequest(form: ResearchForm) {
  const from = parseYear(form.yearFrom);
  const to = parseYear(form.yearTo);
  return {
    question: form.question.trim(),
    max_iterations: form.maxIterations,
    year_from: typeof from === "number" ? from : null,
    year_to: typeof to === "number" ? to : null,
  };
}

/** backend/app/schemas/api/credentials.py: CredentialIn (20–512 chars, no whitespace). */
export function validateApiKey(value: string, provider?: "groq" | "gemini"): string | null {
  const key = value.trim();
  // Groq keys start with "gsk_"; catching a swap here saves a round trip that the provider rejects.
  if (provider === "gemini" && key.startsWith("gsk_")) {
    return "This looks like a Groq key (it starts with gsk_). Paste it into the Groq card instead.";
  }
  if (provider === "groq" && key && !key.startsWith("gsk_")) {
    return "Groq keys start with gsk_. Check that this is not your Gemini key.";
  }
  if (!key) return "Paste the API key from your provider's console.";
  if (/\s/.test(key)) return "API keys contain no spaces or line breaks.";
  if (key.length < 20) return "That looks too short to be an API key.";
  if (key.length > 512) return "That is longer than any supported API key.";
  return null;
}
