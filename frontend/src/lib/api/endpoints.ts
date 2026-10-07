import { ApiClient } from "./client";
import type {
  AgentOutput,
  CredentialStatus,
  Provider,
  RunDetail,
  RunPage,
  RunResult,
  TraceEvent,
  User,
} from "./types";

export type NewRun = {
  question: string;
  max_iterations?: number;
  year_from?: number | null;
  year_to?: number | null;
};

export const EVENTS_PAGE = 200; // the backend's maximum `limit` for /events

/** Typed wrappers for every backend endpoint the frontend uses (nothing else calls fetch). */
export function createApi(client: ApiClient) {
  const get = <T>(path: string, signal?: AbortSignal) => client.request<T>("GET", path, undefined, signal);
  const run = (id: string) => `/runs/${encodeURIComponent(id)}`;

  return {
    client,
    readiness: (signal?: AbortSignal) => get<{ status: string }>("/readyz", signal),

    me: (signal?: AbortSignal) => get<User>("/auth/me", signal),
    login: (email: string, password: string) =>
      client.request<User>("POST", "/auth/login", { email, password }),
    register: (email: string, password: string) =>
      client.request<User>("POST", "/auth/register", { email, password }),
    logout: () => client.request<void>("POST", "/auth/logout"),

    credentials: (signal?: AbortSignal) => get<CredentialStatus[]>("/credentials", signal),
    saveCredential: (provider: Provider, apiKey: string) =>
      client.request<CredentialStatus>("PUT", `/credentials/${provider}`, { api_key: apiKey }),
    deleteCredential: (provider: Provider) =>
      client.request<void>("DELETE", `/credentials/${provider}`),

    createRun: (body: NewRun) => client.request<RunDetail>("POST", "/runs", body),
    listRuns: (limit: number, offset: number, signal?: AbortSignal) =>
      get<RunPage>(`/runs?limit=${limit}&offset=${offset}`, signal),
    getRun: (id: string, signal?: AbortSignal) => get<RunDetail>(run(id), signal),
    cancelRun: (id: string) => client.request<RunDetail>("POST", `${run(id)}/cancel`),
    events: (id: string, after: number, signal?: AbortSignal) =>
      get<TraceEvent[]>(`${run(id)}/events?after=${after}&limit=${EVENTS_PAGE}`, signal),
    outputs: (id: string, signal?: AbortSignal) => get<AgentOutput[]>(`${run(id)}/outputs`, signal),
    result: (id: string, signal?: AbortSignal) => get<RunResult>(`${run(id)}/result`, signal),
  };
}

export type Api = ReturnType<typeof createApi>;

/** The browser-wide instance; the session provider attaches the 401 handler. */
export const api = createApi(new ApiClient());
