"use client";

import { useEffect, useState } from "react";
import type { Session } from "@/lib/session";
import { Wordmark } from "./chrome";

/** Shown while the backend is unreachable, e.g. waking from a Render Free cold start. It shows
 * elapsed time only; there is no invented progress and no agent activity. */
export function WakingScreen({
  session,
  onRetry,
}: {
  session: Extract<Session, { status: "waking" | "unavailable" }>;
  onRetry: () => void;
}) {
  const since = session.status === "waking" ? session.since : null;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (since === null) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [since]);
  const seconds = since === null ? 0 : Math.max(0, Math.round((now - since) / 1000));

  return (
    <main className="waking">
      <div className="waking__inner">
        <Wordmark />
        {session.status === "waking" ? (
          <>
            <div className="waking__signal" aria-hidden="true">
              <span className="pulse" />
            </div>
            <h1 className="waking__title">ResearchPilot is waking the research engine…</h1>
            <p className="lede" role="status" aria-live="polite">
              The backend sleeps when it has not been used for a while and takes up to a minute to start. This page
              continues on its own as soon as it answers.
            </p>
            <p className="mono muted">Waiting {seconds}s</p>
          </>
        ) : (
          <>
            <h1 className="waking__title">The research engine is not answering</h1>
            <p className="lede" role="alert">
              It did not respond within two minutes. It may be down for maintenance, or your connection may be
              interrupted. Your runs and settings are safe on the server.
            </p>
            <div>
              <button type="button" className="button" onClick={onRetry}>
                Try again
              </button>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
