// The one HTTP layer for the browser. Every call goes to the same-origin /api/* path, which
// Next.js rewrites to the backend (next.config.ts). The session lives in the backend's
// httpOnly cookie: this code never reads, stores or sends credentials itself.

export type ApiErrorKind =
  | "unauthorized" // 401: no session, or it expired
  | "forbidden" // 403: e.g. the backend's Origin check
  | "not_found" // 404 (also another user's run)
  | "conflict" // 409
  | "validation" // 422
  | "rate_limited" // 429
  | "server" // 500 from the backend itself
  | "unavailable" // backend unreachable, waking from a cold start, or the proxy failed
  | "network"; // the browser could not reach the frontend's own origin

export type FieldError = { field: string; message: string };

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;
  readonly fieldErrors: FieldError[];

  constructor(kind: ApiErrorKind, status: number, message: string, fieldErrors: FieldError[] = []) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.fieldErrors = fieldErrors;
  }

  /** Safe to retry automatically or offer a retry button for (never for writes by default). */
  get transient(): boolean {
    return this.kind === "unavailable" || this.kind === "network" || this.kind === "rate_limited";
  }
}

type Fetch = typeof fetch;

export type ClientOptions = {
  fetch?: Fetch;
  /** Called on every 401, so the session layer can send the user to sign in. */
  onUnauthorized?: () => void;
};

const GENERIC: Record<ApiErrorKind, string> = {
  unauthorized: "Please sign in to continue.",
  forbidden: "This request was refused.",
  not_found: "Not found.",
  conflict: "This conflicts with the current state.",
  validation: "Some fields need attention.",
  rate_limited: "Too many requests. Wait a moment and try again.",
  server: "The research engine hit an unexpected error.",
  unavailable: "The research engine is not reachable right now.",
  network: "You appear to be offline.",
};

function kindFor(status: number, isJson: boolean): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 422) return "validation";
  if (status === 429) return "rate_limited";
  // 502/503/504 come from the hosting platform or the dev proxy while the backend wakes up;
  // a 500 without the backend's JSON body is the rewrite proxy failing to connect.
  if (status === 502 || status === 503 || status === 504 || !isJson) return "unavailable";
  return "server";
}

/** FastAPI errors are {"detail": string} or, for 422, {"detail": [{loc, msg, type}]}. The
 * backend's 422 handler never echoes submitted values, so these messages are safe to show. */
function parseDetail(body: unknown): { message: string | null; fieldErrors: FieldError[] } {
  if (!body || typeof body !== "object" || !("detail" in body)) {
    return { message: null, fieldErrors: [] };
  }
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") return { message: detail, fieldErrors: [] };
  if (!Array.isArray(detail)) return { message: null, fieldErrors: [] };
  const fieldErrors = detail.flatMap((item): FieldError[] => {
    if (!item || typeof item !== "object") return [];
    const { loc, msg } = item as { loc?: unknown; msg?: unknown };
    const path = Array.isArray(loc) ? loc.filter((p) => p !== "body") : [];
    return [
      {
        field: path.length ? String(path[path.length - 1]) : "",
        message: typeof msg === "string" ? msg.replace(/^Value error, /, "") : "Invalid value",
      },
    ];
  });
  return { message: null, fieldErrors };
}

export class ApiClient {
  private readonly fetchImpl: Fetch;
  onUnauthorized?: () => void;

  constructor(options: ClientOptions = {}) {
    this.fetchImpl = options.fetch ?? ((...args) => globalThis.fetch(...args));
    this.onUnauthorized = options.onUnauthorized;
  }

  async request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    let response: Response;
    try {
      response = await this.fetchImpl(`/api${path}`, {
        method,
        credentials: "same-origin",
        cache: "no-store",
        headers: body === undefined ? { Accept: "application/json" } : {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      const offline = typeof navigator !== "undefined" && navigator.onLine === false;
      const kind: ApiErrorKind = offline ? "network" : "unavailable";
      throw new ApiError(kind, 0, GENERIC[kind]);
    }

    if (response.status === 204) return undefined as T;

    const isJson = (response.headers.get("content-type") ?? "").includes("application/json");
    let parsed: unknown = null;
    if (isJson) {
      try {
        parsed = await response.json();
      } catch {
        parsed = null;
      }
    }

    if (response.ok) {
      if (!isJson) throw new ApiError("unavailable", response.status, GENERIC.unavailable);
      return parsed as T;
    }

    const kind = kindFor(response.status, isJson);
    const { message, fieldErrors } = parseDetail(parsed);
    if (kind === "unauthorized") this.onUnauthorized?.();
    throw new ApiError(kind, response.status, message ?? GENERIC[kind], fieldErrors);
  }
}

/** Human message for any thrown value; never includes stack traces or response bodies. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.fieldErrors.length) {
      return error.fieldErrors.map((e) => (e.field ? `${e.field}: ${e.message}` : e.message)).join(" ");
    }
    return error.message;
  }
  return "Something went wrong. Please try again.";
}
