"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ErrorState, Loading } from "@/components/ui/feedback";
import { api } from "@/lib/api/endpoints";
import type { RunPage } from "@/lib/api/types";
import { RunList } from "./RunList";

const PAGE_SIZE = 20;

export function RunHistory() {
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<RunPage | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  const load = useCallback(async (at: number, signal: AbortSignal) => {
    try {
      const result = await api.listRuns(PAGE_SIZE, at, signal);
      setPage(result);
      setError(null);
    } catch (e) {
      if (!signal.aborted) setError(e);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(offset, controller.signal);
    return () => controller.abort();
  }, [load, offset, attempt]);

  const total = page?.total ?? 0;
  const from = total ? offset + 1 : 0;
  const to = page ? offset + page.items.length : 0;

  return (
    <div className="container page">
      <header className="page__head">
        <div>
          <p className="eyebrow">History</p>
          <h1 className="page__title">Your research</h1>
        </div>
        <Link href="/research" className="button">
          New research
        </Link>
      </header>

      {error && !page ? <ErrorState error={error} what="your runs" onRetry={() => setAttempt((n) => n + 1)} /> : null}
      {!page && !error ? <Loading label="Loading your runs…" /> : null}
      {page ? (
        <>
          {total > 0 ? (
            <p className="small muted history__count" aria-live="polite">
              Showing {from}–{to} of {total}
            </p>
          ) : null}
          <RunList runs={page.items} />
          {total > PAGE_SIZE ? (
            <nav className="pager" aria-label="Pages">
              <button
                type="button"
                className="button button--ghost button--small"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              >
                Newer
              </button>
              <button
                type="button"
                className="button button--ghost button--small"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
              >
                Older
              </button>
            </nav>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
