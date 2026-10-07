import Link from "next/link";
import { SessionLinks } from "./SessionLinks";

export function Wordmark() {
  return (
    <Link href="/" className="wordmark" aria-label="ResearchPilot home">
      <span className="wordmark__mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
          <circle cx="12" cy="12" r="10.25" />
          <path d="M7 15.5V8.5h4.25a2.5 2.5 0 0 1 0 5H7M11.5 13.5l4.5 4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <span>
        Research<em>Pilot</em>
      </span>
    </Link>
  );
}

/** Header for the public pages (landing, sign in, register). */
export function SiteHeader() {
  return (
    <header className="site-header">
      <div className="container site-header__inner">
        <Wordmark />
        <nav aria-label="Primary" className="site-header__nav">
          <Link href="/#agents" className="site-header__link site-header__link--section">
            Agents
          </Link>
          <Link href="/#process" className="site-header__link site-header__link--section">
            Process
          </Link>
          <SessionLinks />
        </nav>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="container site-footer__inner">
        <div>
          <Wordmark />
          <p className="small muted site-footer__note">
            A multi-agent research and literature review system. Built by Team Decepticons.
          </p>
        </div>
        <p className="small muted">
          Literature from OpenAlex and Semantic Scholar. Open-access full text only. Language models run on
          your own free-tier Groq or Gemini key.
        </p>
      </div>
    </footer>
  );
}
