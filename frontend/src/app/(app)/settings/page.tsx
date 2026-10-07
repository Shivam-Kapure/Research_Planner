import type { Metadata } from "next";
import { ProviderSettings } from "@/components/settings/ProviderSettings";

// Rendered only after the backend confirms the session (AppShell), so not an instant navigation.
export const instant = false;

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  return <ProviderSettings />;
}
