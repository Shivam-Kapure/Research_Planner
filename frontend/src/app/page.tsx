import Link from "next/link";
import { SiteFooter, SiteHeader } from "@/components/layout/chrome";
import { WakeBackend } from "@/components/layout/WakeBackend";

// Every statement on this page describes what the system actually does (docs/PHASE6_MULTI_AGENT.md,
// docs/PHASE7_RUNS_API.md). There are no metrics, testimonials or sample results.

const AGENTS = [
  {
    name: "Research Planner",
    role: "Turns your question into an objective, two to six prioritised sub-questions, keywords, a search strategy and inclusion criteria.",
    output: "Research plan",
  },
  {
    name: "Literature Search",
    role: "Queries OpenAlex and Semantic Scholar, removes duplicates, refines weak queries once and screens the candidates against the plan.",
    output: "Selected papers",
  },
  {
    name: "Document Analysis",
    role: "Reads open-access full text where it exists, falls back to the abstract where it does not, and keeps only quotes it can find verbatim in the source.",
    output: "Grounded evidence",
  },
  {
    name: "Evidence Synthesis",
    role: "Measures coverage of every sub-question, finds agreements and contradictions, and decides whether the evidence is sufficient.",
    output: "Verdict and next step",
  },
  {
    name: "Review Writer",
    role: "Writes a structured review in which every claim cites a paper, with references built from metadata and limitations stated plainly.",
    output: "Cited review",
  },
];

const CAPABILITIES = [
  {
    title: "Every handoff is on the record",
    body: "Each agent step, tool call, model call, validation and routing decision is written to an append-only trace that you can inspect while the run is happening.",
  },
  {
    title: "Evidence you can check",
    body: "Claims carry verbatim quotes with page locations. Quotes that cannot be found in the source text are dropped, and the drop is recorded.",
  },
  {
    title: "Honest about its limits",
    body: "When research stops at an iteration or budget limit, or the evidence stays thin or contradictory, the review says so at the top.",
  },
  {
    title: "Your keys, encrypted",
    body: "Bring a free-tier Groq or Gemini key. It is encrypted on the server, never shown again, and never written to traces or logs.",
  },
];

export default function LandingPage() {
  return (
    <>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <WakeBackend />
      <SiteHeader />
      <main id="main" className="landing">
        <section className="hero container" aria-labelledby="hero-title">
          <p className="eyebrow hero__eyebrow">Multi-agent literature review</p>
          <h1 id="hero-title" className="hero__title">
            From research question to <em>evidence‑backed</em> review.
          </h1>
          <div className="hero__foot">
            <p className="lede">
              ResearchPilot coordinates five AI agents that plan the research, search the academic literature, read
              the papers, weigh the evidence and write a cited review. When the evidence falls short, they change
              course on their own.
            </p>
            <div className="hero__actions">
              <Link href="/research" className="button button--large">
                Start a review
              </Link>
              <Link href="#process" className="button button--ghost button--large">
                See how it works
              </Link>
            </div>
          </div>
        </section>

        <section className="manifest" aria-label="What a run produces">
          <div className="container manifest__grid">
            <p className="manifest__lead serif">
              Not a chat. A research process with a plan, a paper trail and a verdict.
            </p>
            <ol className="manifest__list">
              <li>
                <span className="mono">In</span> A question in plain language, optionally bounded by publication years.
              </li>
              <li>
                <span className="mono">Out</span> A structured review with sections, inline citations, references and
                stated limitations.
              </li>
              <li>
                <span className="mono">Also</span> The full execution trace and every intermediate output, from the
                research plan to each paper&apos;s evidence.
              </li>
            </ol>
          </div>
        </section>

        <section id="agents" className="agents container" aria-labelledby="agents-title">
          <header className="section-head">
            <p className="eyebrow">The agents</p>
            <h2 id="agents-title" className="section-head__title">
              Five specialists, one shared record.
            </h2>
            <p className="lede">
              Each agent has its own instructions, inputs and typed output. They hand work to each other through
              validated contracts, never free-form chat.
            </p>
          </header>
          <ol className="agent-list">
            {AGENTS.map((agent, index) => (
              <li key={agent.name} className="agent-list__item">
                <span className="agent-list__index serif" aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <h3 className="agent-list__name">{agent.name}</h3>
                <p className="agent-list__role">{agent.role}</p>
                <p className="agent-list__output">
                  <span className="sr-only">Produces: </span>
                  {agent.output}
                </p>
              </li>
            ))}
          </ol>
        </section>

        <section id="process" className="process" aria-labelledby="process-title">
          <div className="container process__grid">
            <header className="section-head">
              <p className="eyebrow">The process</p>
              <h2 id="process-title" className="section-head__title">
                Research that changes course.
              </h2>
              <p className="lede">
                After every round, Evidence Synthesis checks each sub-question against fixed sufficiency rules. If the
                evidence is not good enough, the run loops back instead of writing a confident review on weak ground.
              </p>
            </header>

            <div className="loop" role="img" aria-label="Plan, search, analyse and synthesise. If evidence is insufficient the search is revised; if it is contradictory the plan is revised. Once sufficient, or at the limit, the review is written.">
              <ol className="loop__main" aria-hidden="true">
                <li>Plan</li>
                <li>Search</li>
                <li>Analyse</li>
                <li>Synthesise</li>
              </ol>
              <div className="loop__branches" aria-hidden="true">
                <div className="loop__branch">
                  <span className="loop__verdict">Insufficient</span>
                  <span className="loop__arrow">revise the search → back to Search</span>
                </div>
                <div className="loop__branch">
                  <span className="loop__verdict">Contradictory</span>
                  <span className="loop__arrow">revise the scope → back to Plan</span>
                </div>
                <div className="loop__branch loop__branch--end">
                  <span className="loop__verdict">Sufficient, or limit reached</span>
                  <span className="loop__arrow">write the review</span>
                </div>
              </div>
            </div>

            <dl className="process__rules">
              <div>
                <dt>Bounded</dt>
                <dd>At most three research iterations, with a fixed budget of model calls and tokens per run.</dd>
              </div>
              <div>
                <dt>Rule-checked</dt>
                <dd>
                  A deterministic validator can overrule the model&apos;s verdict, and when it does, the override is
                  recorded.
                </dd>
              </div>
              <div>
                <dt>Visible</dt>
                <dd>Every loop shows up in the run&apos;s timeline: the verdict, the reasons, and where the run went next.</dd>
              </div>
            </dl>
          </div>
        </section>

        <section className="capabilities container" aria-labelledby="capabilities-title">
          <header className="section-head">
            <p className="eyebrow">Built for scrutiny</p>
            <h2 id="capabilities-title" className="section-head__title">
              A review you can audit.
            </h2>
          </header>
          <div className="capabilities__grid">
            {CAPABILITIES.map((item) => (
              <article key={item.title} className="capability">
                <h3 className="capability__title">{item.title}</h3>
                <p className="muted">{item.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="closing" aria-labelledby="closing-title">
          <div className="container closing__inner">
            <h2 id="closing-title" className="closing__title">
              Start with a question.
            </h2>
            <p className="lede">
              Create an account, add a free-tier Groq or Gemini key, and ask something the literature can answer.
            </p>
            <div className="hero__actions">
              <Link href="/register" className="button button--large">
                Create an account
              </Link>
              <Link href="/login" className="button button--ghost button--large">
                Sign in
              </Link>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
