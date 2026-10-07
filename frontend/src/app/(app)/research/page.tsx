import type { Metadata } from "next";
import { ResearchComposer } from "@/components/research/ResearchComposer";

// Rendered only after the backend confirms the session (AppShell), so not an instant navigation.
export const instant = false;

export const metadata: Metadata = { title: "New research" };

export default function ResearchPage() {
  return <ResearchComposer />;
}
