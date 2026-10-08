"use client";

import { useId, useState, type FormEvent } from "react";
import { ToneBadge } from "@/components/ui/StatusBadge";
import { Notice } from "@/components/ui/feedback";
import { errorMessage } from "@/lib/api/client";
import type { CredentialStatus, Provider } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import type { Tone } from "@/lib/runs/status";
import { validateApiKey } from "@/lib/validation";

export const PROVIDERS: Record<Provider, { name: string; console: string; consoleLabel: string; role: string }> = {
  groq: {
    name: "Groq",
    console: "https://console.groq.com/keys",
    consoleLabel: "GroqCloud console",
    role: "Preferred for planning, search and document analysis.",
  },
  gemini: {
    name: "Gemini",
    console: "https://aistudio.google.com/apikey",
    consoleLabel: "Google AI Studio",
    role: "Preferred for evidence synthesis and review writing.",
  },
};

const STATUS: Record<string, { tone: Tone; label: string; detail: string }> = {
  valid: { tone: "positive", label: "Verified", detail: "The provider accepted this key." },
  invalid: {
    tone: "negative",
    label: "Rejected",
    detail: "The provider rejected this key. Runs will not use it until you replace it.",
  },
  unverified: {
    tone: "caution",
    label: "Not verified",
    detail: "The provider could not be reached when the key was saved. It will be used, and checked on use.",
  },
};

/** The stored key is never available to the browser; only its last four characters are shown. */
export function maskedKey(hint: string | null): string {
  return `••••••••••••${hint ?? "••••"}`;
}

export function CredentialCard({
  credential,
  onSave,
  onDelete,
}: {
  credential: CredentialStatus;
  onSave: (provider: Provider, key: string) => Promise<CredentialStatus>;
  onDelete: (provider: Provider) => Promise<void>;
}) {
  const id = useId();
  const meta = PROVIDERS[credential.provider];
  const [editing, setEditing] = useState(!credential.configured);
  // The key exists only in this input's state until it is sent; it is cleared right after.
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "delete" | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [saved, setSaved] = useState<{ ok: boolean; text: string } | null>(null);
  const status = credential.status ? STATUS[credential.status] : null;

  async function save(event: FormEvent) {
    event.preventDefault();
    const problem = validateApiKey(key, credential.provider);
    setError(problem);
    setSaved(null);
    if (problem) return;
    setBusy("save");
    try {
      const result = await onSave(credential.provider, key.trim());
      setKey("");
      setEditing(false);
      setSaved(
        result.status === "valid"
          ? { ok: true, text: "Saved and verified with the provider." }
          : result.status === "invalid"
            ? { ok: false, text: "Saved, but the provider rejected the key. Check it and try again." }
            : { ok: true, text: "Saved. The provider could not be reached to verify it." },
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    setBusy("delete");
    setError(null);
    try {
      await onDelete(credential.provider);
      setConfirming(false);
      setSaved(null);
      setEditing(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="credential" aria-labelledby={`${id}-title`}>
      <header className="credential__head">
        <div>
          <h2 id={`${id}-title`} className="credential__name">
            {meta.name}
          </h2>
          <p className="small muted">{meta.role}</p>
        </div>
        {credential.configured && status ? (
          <ToneBadge tone={status.tone}>{status.label}</ToneBadge>
        ) : (
          <ToneBadge tone="neutral">Not added</ToneBadge>
        )}
      </header>

      {credential.configured ? (
        <dl className="credential__facts">
          <div>
            <dt>Stored key</dt>
            <dd className="mono" aria-label={`Key ending in ${credential.key_hint ?? "unknown"}`}>
              {maskedKey(credential.key_hint)}
            </dd>
          </div>
          {credential.updated_at ? (
            <div>
              <dt>Updated</dt>
              <dd>{formatDateTime(credential.updated_at)}</dd>
            </div>
          ) : null}
          {status ? (
            <div className="credential__fact-wide">
              <dt>Status</dt>
              <dd>{status.detail}</dd>
            </div>
          ) : null}
        </dl>
      ) : (
        <p className="credential__empty">
          No {meta.name} key yet. Create a free key in the{" "}
          <a className="text-link" href={meta.console} target="_blank" rel="noopener noreferrer">
            {meta.consoleLabel}
          </a>
          , then paste it below. No billing is needed.
        </p>
      )}

      {saved ? (
        <p className={saved.ok ? "credential__saved" : "field__error"} role="status">
          {saved.text}
        </p>
      ) : null}

      {editing ? (
        <form className="credential__form" onSubmit={save} noValidate>
          <div className="field">
            <label className="field__label" htmlFor={`${id}-key`}>
              {credential.configured ? `Replace the ${meta.name} key` : `${meta.name} API key`}
            </label>
            <input
              id={`${id}-key`}
              className="input mono-input"
              type="password"
              name={`${credential.provider}-api-key`}
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${id}-error` : `${id}-hint`}
            />
            <p className="field__hint" id={`${id}-hint`}>
              Sent once over the session, encrypted by the server, and never shown again.
            </p>
            {error ? (
              <p className="field__error" id={`${id}-error`} role="alert">
                {error}
              </p>
            ) : null}
          </div>
          <div className="credential__actions">
            <button type="submit" className="button button--small" disabled={busy !== null}>
              {busy === "save" ? "Saving and verifying…" : "Save key"}
            </button>
            {credential.configured ? (
              <button
                type="button"
                className="button button--ghost button--small"
                onClick={() => {
                  setEditing(false);
                  setKey("");
                  setError(null);
                }}
              >
                Keep current key
              </button>
            ) : null}
          </div>
        </form>
      ) : (
        <div className="credential__actions">
          <button type="button" className="button button--ghost button--small" onClick={() => setEditing(true)}>
            Replace key
          </button>
          {!confirming ? (
            <button type="button" className="button button--danger button--small" onClick={() => setConfirming(true)}>
              Remove key
            </button>
          ) : null}
        </div>
      )}

      {confirming ? (
        <Notice
          tone="negative"
          title={`Remove the ${meta.name} key?`}
          actions={
            <>
              <button type="button" className="button button--danger button--small" onClick={remove} disabled={busy !== null}>
                {busy === "delete" ? "Removing…" : "Yes, remove it"}
              </button>
              <button type="button" className="button button--ghost button--small" onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </>
          }
        >
          <p>New runs will not be able to use {meta.name}. Runs already finished are not affected.</p>
        </Notice>
      ) : null}
      {error && !editing ? (
        <p className="field__error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
