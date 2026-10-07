"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Loading } from "@/components/ui/feedback";
import { useSession } from "@/lib/session";
import { Wordmark } from "./chrome";
import { WakingScreen } from "./WakingScreen";

const NAV = [
  { href: "/research", label: "New research" },
  { href: "/runs", label: "History" },
  { href: "/settings", label: "Settings" },
];

/** Authenticated area: resolves the session, waits out a cold start, or sends to sign in. */
export function AppShell({ children }: { children: ReactNode }) {
  const { session, signOut, retry } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const leaving = useRef(false); // signing out goes to the home page, not to sign-in

  useEffect(() => {
    if (session.status !== "anonymous" || leaving.current) return;
    const params = new URLSearchParams({ next: pathname });
    if (session.expired) params.set("expired", "1");
    router.replace(`/login?${params.toString()}`);
  }, [session, pathname, router]);

  if (session.status === "waking" || session.status === "unavailable") {
    return <WakingScreen session={session} onRetry={retry} />;
  }
  if (session.status !== "authenticated") {
    return (
      <main className="container">
        <Loading page label={session.status === "anonymous" ? "Redirecting to sign in…" : "Opening your workspace…"} />
      </main>
    );
  }

  return (
    <>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <header className="app-header">
        <div className="container app-header__inner">
          <Wordmark />
          <nav aria-label="Workspace" className="app-header__nav">
            {NAV.map((item) => {
              const active = item.href === "/runs" ? pathname.startsWith("/runs") : pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className="app-header__link"
                  aria-current={active ? "page" : undefined}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <AccountMenu
            email={session.user.email}
            onSignOut={async () => {
              leaving.current = true;
              router.replace("/");
              await signOut();
            }}
          />
        </div>
      </header>
      <main id="main" className="app-main">
        {children}
      </main>
    </>
  );
}

function AccountMenu({ email, onSignOut }: { email: string; onSignOut: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="app-header__account">
      <span className="app-header__email break" title={email}>
        {email}
      </span>
      <button
        type="button"
        className="button button--ghost button--small"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onSignOut();
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Signing out…" : "Sign out"}
      </button>
    </div>
  );
}
