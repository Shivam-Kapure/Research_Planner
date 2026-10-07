"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useState, type FormEvent } from "react";
import { Notice } from "@/components/ui/feedback";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { useSession } from "@/lib/session";
import { validateCredentials, type Errors } from "@/lib/validation";

type Mode = "login" | "register";

/** Only same-site paths are honoured as a post-login destination. */
function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return "/research";
  return value;
}

const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

function failureMessage(error: unknown, mode: Mode): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Please try again.";
  switch (error.kind) {
    case "unauthorized":
      return "That email and password do not match an account.";
    case "conflict":
      return "This email cannot be registered. If you already have an account, sign in instead.";
    case "validation":
      return error.fieldErrors.map((e) => e.message).join(" ") || "Check the details and try again.";
    case "rate_limited":
      return "Too many attempts. Wait a minute and try again.";
    case "unavailable":
    case "network":
      return "The research engine is not reachable. It may be waking up; try again in a moment.";
    default:
      return mode === "login" ? "Sign in failed. Please try again." : "Registration failed. Please try again.";
  }
}

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const expired = params.get("expired") === "1";
  const { session, signIn } = useSession();
  const id = useId();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Errors<"email" | "password">>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (session.status === "authenticated") router.replace(next);
  }, [session.status, next, router]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const found = validateCredentials(email, password, mode);
    setErrors(found);
    setFailure(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      if (mode === "register") await api.register(email.trim(), password);
      await signIn(email.trim(), password);
      setPassword("");
      router.replace(next);
    } catch (error) {
      // Field-level 422s (e.g. an address the backend's email validator rejects) go next to the field.
      const fields =
        error instanceof ApiError && error.kind === "validation"
          ? error.fieldErrors.filter((e) => e.field === "email" || e.field === "password")
          : [];
      if (fields.length) {
        setErrors(Object.fromEntries(fields.map((e) => [e.field, sentence(e.message)])));
      } else {
        setFailure(failureMessage(error, mode));
      }
      setBusy(false);
    }
  }

  const isLogin = mode === "login";
  return (
    <div className="auth">
      <div className="auth__intro">
        <p className="eyebrow">{isLogin ? "Welcome back" : "Create an account"}</p>
        <h1 className="auth__title">{isLogin ? "Sign in to your research workspace" : "Start your first literature review"}</h1>
        <p className="muted">
          {isLogin
            ? "Your runs, traces and reviews are kept with your account."
            : "An account keeps your runs and your encrypted provider keys. No email verification, no billing."}
        </p>
      </div>

      {expired ? (
        <Notice tone="caution" title="Your session expired">
          <p>Sign in again to pick up where you left off.</p>
        </Notice>
      ) : null}

      <form className="auth__form" onSubmit={submit} noValidate aria-describedby={failure ? `${id}-failure` : undefined}>
        {failure ? (
          <div id={`${id}-failure`}>
            <Notice tone="negative" role="alert" title={isLogin ? "Could not sign in" : "Could not create the account"}>
              <p>{failure}</p>
            </Notice>
          </div>
        ) : null}

        <div className="field">
          <label className="field__label" htmlFor={`${id}-email`}>
            Email
          </label>
          <input
            id={`${id}-email`}
            className="input"
            type="email"
            name="email"
            autoComplete="email"
            inputMode="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={errors.email ? true : undefined}
            aria-describedby={errors.email ? `${id}-email-error` : undefined}
            required
          />
          {errors.email ? (
            <p className="field__error" id={`${id}-email-error`}>
              {errors.email}
            </p>
          ) : null}
        </div>

        <div className="field">
          <label className="field__label" htmlFor={`${id}-password`}>
            Password
          </label>
          <input
            id={`${id}-password`}
            className="input"
            type="password"
            name="password"
            autoComplete={isLogin ? "current-password" : "new-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={errors.password ? true : undefined}
            aria-describedby={`${id}-password-hint${errors.password ? ` ${id}-password-error` : ""}`}
            required
          />
          {!isLogin && !errors.password ? (
            <p className="field__hint" id={`${id}-password-hint`}>
              At least 10 characters.
            </p>
          ) : (
            <span id={`${id}-password-hint`} hidden />
          )}
          {errors.password ? (
            <p className="field__error" id={`${id}-password-error`}>
              {errors.password}
            </p>
          ) : null}
        </div>

        <button type="submit" className="button button--large auth__submit" disabled={busy}>
          {busy ? (isLogin ? "Signing in…" : "Creating account…") : isLogin ? "Sign in" : "Create account"}
        </button>

        <p className="small muted auth__switch">
          {isLogin ? "New to ResearchPilot? " : "Already have an account? "}
          <Link
            className="text-link"
            href={`${isLogin ? "/register" : "/login"}${next !== "/research" ? `?next=${encodeURIComponent(next)}` : ""}`}
          >
            {isLogin ? "Create an account" : "Sign in"}
          </Link>
        </p>
      </form>
    </div>
  );
}
