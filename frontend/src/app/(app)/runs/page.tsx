import type { Metadata } from "next";
import { RunHistory } from "@/components/runs/RunHistory";

// Rendered only after the backend confirms the session (AppShell), so not an instant navigation.
export const instant = false;

export const metadata: Metadata = { title: "History" };

export default function RunsPage() {
  return <RunHistory />;
}
