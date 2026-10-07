import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthForm } from "@/components/auth/AuthForm";
import { Loading } from "@/components/ui/feedback";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <Suspense fallback={<Loading page label="Loading…" />}>
      <AuthForm mode="login" />
    </Suspense>
  );
}
