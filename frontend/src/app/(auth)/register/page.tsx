import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthForm } from "@/components/auth/AuthForm";
import { Loading } from "@/components/ui/feedback";

export const metadata: Metadata = { title: "Create an account" };

export default function RegisterPage() {
  return (
    <Suspense fallback={<Loading page label="Loading…" />}>
      <AuthForm mode="register" />
    </Suspense>
  );
}
