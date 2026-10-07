import { SiteHeader } from "@/components/layout/chrome";
import { SessionProvider } from "@/lib/session";

export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <SessionProvider probe={false}>
      <SiteHeader />
      <main id="main" className="auth-main">
        {children}
      </main>
    </SessionProvider>
  );
}
