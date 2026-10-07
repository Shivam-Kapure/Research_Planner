import type { Metadata } from "next";
import { Suspense } from "react";
import { RunView } from "@/components/runs/RunView";
import { Loading } from "@/components/ui/feedback";

// Rendered only after the backend confirms the session (AppShell), so not an instant navigation.
export const instant = false;

export const metadata: Metadata = { title: "Run" };

export default function RunPage({ params }: PageProps<"/runs/[runId]">) {
  return (
    <Suspense fallback={<Loading page label="Opening the run…" />}>
      <RunView params={params} />
    </Suspense>
  );
}
