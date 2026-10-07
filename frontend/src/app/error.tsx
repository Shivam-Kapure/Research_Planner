"use client";

import { useEffect } from "react";

/** Last-resort boundary for rendering errors. Shows no internals; details stay in the console. */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <main id="main" className="container page not-found">
      <p className="eyebrow">Something went wrong</p>
      <h1 className="page__title">This page could not be displayed.</h1>
      <p className="lede">Your runs are safe on the server. Try again, or go back to your workspace.</p>
      <div className="hero__actions">
        <button type="button" className="button" onClick={reset}>
          Try again
        </button>
        <a href="/research" className="button button--ghost">
          Back to the workspace
        </a>
      </div>
    </main>
  );
}
