import Link from "next/link";
import { SiteHeader } from "@/components/layout/chrome";

export default function NotFound() {
  return (
    <>
      <SiteHeader />
      <main id="main" className="container page not-found">
        <p className="eyebrow">404</p>
        <h1 className="page__title">This page is not in the record.</h1>
        <p className="lede">The address may be mistyped, or the page has moved.</p>
        <div className="hero__actions">
          <Link href="/" className="button">
            Go to the home page
          </Link>
          <Link href="/runs" className="button button--ghost">
            Your research history
          </Link>
        </div>
      </main>
    </>
  );
}
