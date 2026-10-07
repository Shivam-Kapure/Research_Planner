"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useState, type FormEvent } from "react";
import { RunList } from "@/components/runs/RunList";
import { ErrorState, Loading, Notice } from "@/components/ui/feedback";
import { ApiError, errorMessage } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { CredentialStatus, RunSummary } from "@/lib/api/types";
import { isActive } from "@/lib/runs/status";
import {
  QUESTION_MAX,
  QUESTION_MIN,
  toResearchRequest,
  validateResearch,
  type Errors,
  type ResearchForm,
} from "@/lib/validation";

type Context = {
  credentials: CredentialStatus[] | null;
  recent: RunSummary[] | null;
  error: unknown;
};

const FIELD_FOR: Record<string, keyof ResearchForm> = {
  question: "question",
  year_from: "yearFrom",
  year_to: "yearTo",
  max_iterations: "maxIterations",
};

export function ResearchComposer() {
  const router = useRouter();
  const id = useId();
  const [form, setForm] = useState<ResearchForm>({ question: "", maxIterations: 3, yearFrom: "", yearTo: "" });
  const [errors, setErrors] = useState<Errors<"question" | "yearFrom" | "yearTo">>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [context, setContext] = useState<Context>({ credentials: null, recent: null, error: null });

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const [credentials, page] = await Promise.all([api.credentials(signal), api.listRuns(5, 0, signal)]);
      setContext({ credentials, recent: page.items, error: null });
    } catch (error) {
      if (signal?.aborted) return;
      setContext((c) => ({ ...c, error }));
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const configured = context.credentials?.filter((c) => c.configured && c.status !== "invalid") ?? null;
  const noProvider = configured !== null && configured.length === 0;
  const activeRun = context.recent?.find((r) => isActive(r.status)) ?? null;
  const length = form.question.trim().length;

  function update<K extends keyof ResearchForm>(key: K, value: ResearchForm[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    if (key in errors) setErrors((e) => ({ ...e, [key]: undefined }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const found = validateResearch(form);
    setErrors(found);
    setFailure(null);
    if (Object.values(found).some(Boolean)) return;
    setBusy(true);
    try {
      const run = await api.createRun(toResearchRequest(form));
      router.push(`/runs/${run.id}`);
    } catch (error) {
      setBusy(false);
      if (error instanceof ApiError && error.kind === "validation") {
        const mapped: Errors<"question" | "yearFrom" | "yearTo"> = {};
        const general: string[] = [];
        for (const fe of error.fieldErrors) {
          const key = FIELD_FOR[fe.field];
          if (key && key !== "maxIterations") mapped[key] = fe.message;
          else general.push(fe.message);
        }
        setErrors(mapped);
        if (general.length) setFailure(general.join(" "));
      } else if (error instanceof ApiError && error.kind === "conflict") {
        setFailure("You already have a run in progress. Open it below, or wait for it to finish.");
        void load();
      } else {
        setFailure(errorMessage(error));
      }
    }
  }

  return (
    <div className="workspace container">
      <form className="composer" onSubmit={submit} noValidate>
        <div className="composer__main">
          <label htmlFor={`${id}-q`} className="composer__label">
            <span className="eyebrow">New literature review</span>
            <span className="composer__prompt">What should the literature tell you?</span>
          </label>
          <textarea
            id={`${id}-q`}
            className="composer__question"
            value={form.question}
            onChange={(e) => update("question", e.target.value)}
            placeholder="e.g. What is the effect of regular aerobic exercise on blood pressure in adults with hypertension?"
            rows={4}
            maxLength={QUESTION_MAX + 200}
            aria-invalid={errors.question ? true : undefined}
            aria-describedby={`${id}-q-hint${errors.question ? ` ${id}-q-error` : ""}`}
          />
          <div className="composer__meta">
            <p id={`${id}-q-hint`} className="small muted">
              Ask one focused question. Name the population, intervention or outcome you care about.
            </p>
            <p className={`mono ${length > QUESTION_MAX ? "composer__count--over" : "muted"}`} aria-live="polite">
              {length < QUESTION_MIN ? `${QUESTION_MIN - length} more to go` : `${length} / ${QUESTION_MAX}`}
            </p>
          </div>
          {errors.question ? (
            <p className="field__error" id={`${id}-q-error`}>
              {errors.question}
            </p>
          ) : null}

          <fieldset className="composer__options">
            <legend className="sr-only">Research settings</legend>
            <div className="field">
              <span className="field__label" id={`${id}-iter`}>
                Research iterations
              </span>
              <div className="segmented" role="radiogroup" aria-labelledby={`${id}-iter`}>
                {[1, 2, 3].map((n) => (
                  <label key={n} className="segmented__option">
                    <input
                      type="radio"
                      name="max_iterations"
                      value={n}
                      checked={form.maxIterations === n}
                      onChange={() => update("maxIterations", n)}
                    />
                    <span>{n}</span>
                  </label>
                ))}
              </div>
              <p className="field__hint">The most rounds of search and synthesis the agents may run.</p>
            </div>
            <div className="field">
              <span className="field__label">Publication years (optional)</span>
              <div className="composer__years">
                <label className="sr-only" htmlFor={`${id}-from`}>
                  From year
                </label>
                <input
                  id={`${id}-from`}
                  className="input"
                  inputMode="numeric"
                  placeholder="From"
                  value={form.yearFrom}
                  onChange={(e) => update("yearFrom", e.target.value)}
                  aria-invalid={errors.yearFrom ? true : undefined}
                  maxLength={4}
                />
                <span aria-hidden="true" className="muted">
                  –
                </span>
                <label className="sr-only" htmlFor={`${id}-to`}>
                  To year
                </label>
                <input
                  id={`${id}-to`}
                  className="input"
                  inputMode="numeric"
                  placeholder="To"
                  value={form.yearTo}
                  onChange={(e) => update("yearTo", e.target.value)}
                  aria-invalid={errors.yearTo ? true : undefined}
                  maxLength={4}
                />
              </div>
              {errors.yearFrom ? <p className="field__error">{errors.yearFrom}</p> : null}
              {errors.yearTo ? <p className="field__error">{errors.yearTo}</p> : null}
            </div>
          </fieldset>

          {failure ? (
            <Notice tone="negative" role="alert" title="The run was not started">
              <p>{failure}</p>
            </Notice>
          ) : null}

          <div className="composer__submit">
            <button
              type="submit"
              className="button button--large"
              disabled={busy || noProvider || activeRun !== null}
            >
              {busy ? "Starting the agents…" : "Begin research"}
            </button>
            {busy ? <Loading label="Creating the run" /> : null}
          </div>
        </div>

        <aside className="composer__aside" aria-label="Before you start">
          <ProviderReadiness credentials={context.credentials} error={context.error} onRetry={() => void load()} />
          {activeRun ? (
            <Notice
              tone="active"
              title="A run is already in progress"
              actions={
                <Link href={`/runs/${activeRun.id}`} className="button button--small">
                  Open the live run
                </Link>
              }
            >
              <p className="break">“{activeRun.question}”</p>
              <p>One run at a time per account. You can start another when it finishes or is cancelled.</p>
            </Notice>
          ) : null}
          <div className="composer__howto">
            <p className="eyebrow">What happens next</p>
            <ol>
              <li>The planner breaks your question into prioritised sub-questions.</li>
              <li>Search, analysis and synthesis run, and you can watch each step live.</li>
              <li>If the evidence is weak or conflicting, the agents revise the search or the scope and go again.</li>
              <li>The writer produces a cited review, stating any limitations.</li>
            </ol>
            <p className="small muted">A run usually takes several minutes. You can leave the page; it keeps running.</p>
          </div>
        </aside>
      </form>

      <section className="workspace__recent" aria-labelledby={`${id}-recent`}>
        <div className="workspace__recent-head">
          <h2 id={`${id}-recent`} className="workspace__h2">
            Recent research
          </h2>
          <Link href="/runs" className="text-link small">
            All history
          </Link>
        </div>
        {context.recent === null && !context.error ? <Loading label="Loading your recent runs…" /> : null}
        {context.recent ? (
          <RunList
            runs={context.recent}
            empty="Your first run will appear here. Ask a question above to begin."
          />
        ) : null}
      </section>
    </div>
  );
}

function ProviderReadiness({
  credentials,
  error,
  onRetry,
}: {
  credentials: CredentialStatus[] | null;
  error: unknown;
  onRetry: () => void;
}) {
  if (error && !credentials) return <ErrorState error={error} what="your provider settings" onRetry={onRetry} />;
  if (!credentials) return <Loading label="Checking your model providers…" />;
  const usable = credentials.filter((c) => c.configured && c.status !== "invalid");
  const invalid = credentials.filter((c) => c.configured && c.status === "invalid");
  if (!usable.length) {
    return (
      <Notice
        tone="caution"
        title="Add a model provider first"
        actions={
          <Link href="/settings" className="button button--small">
            Add an API key
          </Link>
        }
      >
        <p>
          The agents need a free-tier Groq or Gemini key to think with.
          {invalid.length ? " Your saved key was rejected by the provider." : ""} Keys are encrypted on the server.
        </p>
      </Notice>
    );
  }
  return (
    <div className="readiness">
      <p className="eyebrow">Model providers</p>
      <ul className="readiness__list">
        {credentials.map((c) => (
          <li key={c.provider}>
            <span>{c.provider === "groq" ? "Groq" : "Gemini"}</span>
            <span className="muted small">
              {!c.configured ? "Not added" : c.status === "valid" ? "Ready" : c.status === "invalid" ? "Rejected" : "Added, not verified"}
            </span>
          </li>
        ))}
      </ul>
      <Link href="/settings" className="text-link small">
        Manage keys
      </Link>
    </div>
  );
}
