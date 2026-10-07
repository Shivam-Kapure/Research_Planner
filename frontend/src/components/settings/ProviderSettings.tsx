"use client";

import { useCallback, useEffect, useState } from "react";
import { ErrorState, Loading, Notice } from "@/components/ui/feedback";
import { api } from "@/lib/api/endpoints";
import type { CredentialStatus, Provider } from "@/lib/api/types";
import { CredentialCard } from "./CredentialCard";

export function ProviderSettings() {
  const [credentials, setCredentials] = useState<CredentialStatus[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  const load = useCallback(async (signal: AbortSignal) => {
    try {
      setCredentials(await api.credentials(signal));
      setError(null);
    } catch (e) {
      if (!signal.aborted) setError(e);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(controller.signal);
    return () => controller.abort();
  }, [load, attempt]);

  const save = async (provider: Provider, key: string) => {
    const updated = await api.saveCredential(provider, key);
    setCredentials((list) => list?.map((c) => (c.provider === provider ? updated : c)) ?? [updated]);
    return updated;
  };

  const remove = async (provider: Provider) => {
    await api.deleteCredential(provider);
    setCredentials(
      (list) =>
        list?.map((c) =>
          c.provider === provider
            ? { provider, configured: false, key_hint: null, status: null, validated_at: null, updated_at: null }
            : c,
        ) ?? null,
    );
  };

  const none = credentials !== null && !credentials.some((c) => c.configured);

  return (
    <div className="container page settings">
      <header className="page__head">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 className="page__title">Model providers</h1>
          <p className="lede">
            The agents reason with your own free-tier keys. Add Groq, Gemini or both; with both, each agent uses its
            preferred provider and falls back to the other.
          </p>
        </div>
      </header>

      <div className="settings__body">
        <div className="settings__cards">
          {error && !credentials ? (
            <ErrorState error={error} what="your providers" onRetry={() => setAttempt((n) => n + 1)} />
          ) : null}
          {!credentials && !error ? <Loading label="Loading your providers…" /> : null}
          {none ? (
            <Notice tone="caution" title="No provider configured yet">
              <p>Research runs need at least one key. Add either provider below to start your first review.</p>
            </Notice>
          ) : null}
          {credentials?.map((c) => (
            <CredentialCard key={c.provider} credential={c} onSave={save} onDelete={remove} />
          ))}
        </div>
        <aside className="settings__aside" aria-label="How keys are handled">
          <p className="eyebrow">How your keys are handled</p>
          <ul className="settings__points">
            <li>Encrypted on the server before storage. Only the last four characters are ever shown back.</li>
            <li>Never stored in this browser, in cookies you can read, in URLs, traces or logs.</li>
            <li>Checked with the provider when saved. A key the provider later rejects is marked and skipped.</li>
            <li>Free tiers are enough. ResearchPilot never asks you to enable billing.</li>
          </ul>
        </aside>
      </div>
    </div>
  );
}
