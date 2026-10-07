import { Suspense } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { Loading } from "@/components/ui/feedback";
import { SessionProvider } from "@/lib/session";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <SessionProvider>
      <Suspense fallback={<Loading page label="Opening your workspace…" />}>
        <AppShell>{children}</AppShell>
      </Suspense>
    </SessionProvider>
  );
}
