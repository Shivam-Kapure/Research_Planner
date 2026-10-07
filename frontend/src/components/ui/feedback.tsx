import type { ReactNode } from "react";
import { ApiError } from "@/lib/api/client";
import type { Tone } from "@/lib/runs/status";
import { AlertIcon, CheckIcon, CrossIcon, InfoIcon } from "./icons";

export function Notice({
  tone = "neutral",
  title,
  children,
  actions,
  role,
}: {
  tone?: Tone;
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  role?: "status" | "alert";
}) {
  const Icon = tone === "positive" ? CheckIcon : tone === "negative" ? CrossIcon : tone === "caution" ? AlertIcon : InfoIcon;
  return (
    <div className={`notice tone-${tone}`} role={role}>
      <Icon className="notice__icon" />
      <div>
        <p className="notice__title">{title}</p>
        {children ? <div className="notice__body">{children}</div> : null}
        {actions ? <div className="notice__actions">{actions}</div> : null}
      </div>
    </div>
  );
}

export function EmptyState({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="empty">
      <p className="empty__title">{title}</p>
      <div className="empty__body">{children}</div>
      {actions ? <div className="empty__actions">{actions}</div> : null}
    </div>
  );
}

export function Loading({ label, page = false }: { label: string; page?: boolean }) {
  return (
    <div className={page ? "loading loading--page" : "loading"} role="status" aria-live="polite">
      <span className="pulse" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

const ERROR_COPY: Record<string, { title: string; body: string }> = {
  unauthorized: { title: "Your session has ended", body: "Sign in again to continue." },
  forbidden: {
    title: "The request was refused",
    body: "The backend did not accept this request from this page. Reload and try again.",
  },
  not_found: {
    title: "Not found",
    body: "It may have been removed, or it belongs to a different account.",
  },
  rate_limited: {
    title: "Too many requests",
    body: "The server asked us to slow down. Wait a moment, then try again.",
  },
  server: {
    title: "The research engine hit an error",
    body: "This was not caused by anything you did. Try again shortly.",
  },
  unavailable: {
    title: "The research engine is not reachable",
    body: "It may be starting up after a period of inactivity, or briefly offline. Try again in a moment.",
  },
  network: { title: "You appear to be offline", body: "Check your connection and try again." },
};

/** User-facing explanation of a failed request; never shows stack traces or raw bodies. */
export function ErrorState({ error, onRetry, what }: { error: unknown; onRetry?: () => void; what?: string }) {
  const kind = error instanceof ApiError ? error.kind : "server";
  const copy = ERROR_COPY[kind] ?? {
    title: what ? `Could not load ${what}` : "Something went wrong",
    body: error instanceof ApiError ? error.message : "Please try again.",
  };
  const retryable = !(error instanceof ApiError) || !["unauthorized", "not_found", "forbidden"].includes(error.kind);
  return (
    <Notice
      tone="negative"
      role="alert"
      title={what && kind !== "not_found" ? `Could not load ${what}` : copy.title}
      actions={
        onRetry && retryable ? (
          <button type="button" className="button button--ghost button--small" onClick={onRetry}>
            Try again
          </button>
        ) : null
      }
    >
      <p>{what && kind !== "not_found" ? `${copy.title}. ${copy.body}` : copy.body}</p>
    </Notice>
  );
}
