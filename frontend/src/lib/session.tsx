"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError } from "./api/client";
import { api } from "./api/endpoints";
import type { User } from "./api/types";

// Session state comes only from the backend (GET /api/auth/me with its httpOnly cookie).
// Nothing about the session is stored in the browser by this code.

export type Session =
  | { status: "loading" }
  | { status: "authenticated"; user: User }
  | { status: "anonymous"; expired: boolean }
  | { status: "waking"; since: number } // backend not reachable yet (e.g. Render cold start)
  | { status: "unavailable" }; // still unreachable after the wake window

type SessionApi = {
  session: Session;
  signIn: (email: string, password: string) => Promise<User>;
  signOut: () => Promise<void>;
  retry: () => void;
};

const SessionContext = createContext<SessionApi | null>(null);

const WAKE_WINDOW_MS = 120_000; // Render Free can take about a minute to wake
const PROBE_EVERY_MS = 3_000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** `probe={false}` skips the initial GET /api/auth/me (the sign-in pages do not need it, and an
 * anonymous probe is a 401 the browser logs). */
export function SessionProvider({ children, probe = true }: { children: ReactNode; probe?: boolean }) {
  const [session, setSession] = useState<Session>(probe ? { status: "loading" } : { status: "anonymous", expired: false });
  const [shouldProbe, setShouldProbe] = useState(probe);
  const [attempt, setAttempt] = useState(0);
  const sessionRef = useRef(session);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  // Any 401 while signed in means the session expired or was revoked.
  useEffect(() => {
    api.client.onUnauthorized = () => {
      if (sessionRef.current.status === "authenticated") setSession({ status: "anonymous", expired: true });
    };
    return () => {
      api.client.onUnauthorized = undefined;
    };
  }, []);

  useEffect(() => {
    if (!shouldProbe) return;
    const controller = new AbortController();
    const { signal } = controller;
    const started = Date.now();

    async function resolve(): Promise<void> {
      while (!signal.aborted) {
        try {
          const user = await api.me(signal);
          if (!signal.aborted) setSession({ status: "authenticated", user });
          return;
        } catch (error) {
          if (signal.aborted) return;
          if (error instanceof ApiError && error.kind === "unauthorized") {
            setSession({ status: "anonymous", expired: false });
            return;
          }
          if (!(error instanceof ApiError) || !error.transient) {
            setSession({ status: "unavailable" });
            return;
          }
        }
        // Waking: probe readiness until the backend answers, then ask /me again.
        setSession({ status: "waking", since: started });
        while (!signal.aborted) {
          if (Date.now() - started > WAKE_WINDOW_MS) {
            setSession({ status: "unavailable" });
            return;
          }
          await sleep(PROBE_EVERY_MS);
          try {
            await api.readiness(signal);
            break;
          } catch {
            // still waking
          }
        }
      }
    }

    void resolve();
    return () => controller.abort();
  }, [attempt, shouldProbe]);

  const signIn = useCallback(async (email: string, password: string) => {
    const user = await api.login(email, password);
    setSession({ status: "authenticated", user });
    return user;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setSession({ status: "anonymous", expired: false });
    }
  }, []);

  const retry = useCallback(() => {
    setSession({ status: "loading" });
    setShouldProbe(true);
    setAttempt((n) => n + 1);
  }, []);

  const value = useMemo(() => ({ session, signIn, signOut, retry }), [session, signIn, signOut, retry]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionApi {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}
