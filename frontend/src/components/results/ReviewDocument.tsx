import { ToneBadge } from "@/components/ui/StatusBadge";
import type { FinalReview, Reference } from "@/lib/api/types";
import { formatAuthors } from "@/lib/format";
import { Markdown } from "@/lib/markdown";
import type { Tone } from "@/lib/runs/status";

export const EVIDENCE_STATUS: Record<FinalReview["evidence_status"], { tone: Tone; label: string; meaning: string }> = {
  sufficient: {
    tone: "positive",
    label: "Evidence sufficient",
    meaning:
      "Every priority-1 sub-question was covered by at least two papers, one read in full text, and none was left without evidence.",
  },
  limited: {
    tone: "caution",
    label: "Evidence limited",
    meaning: "Some sub-questions are weakly covered or missing. Treat conclusions as provisional.",
  },
  contradictory: {
    tone: "negative",
    label: "Evidence contradictory",
    meaning: "Studies disagree on at least one priority sub-question and the disagreement is unresolved.",
  },
};

const refId = (key: string) => `ref-${key.replace(/[^A-Za-z0-9_-]/g, "_")}`;

function Citation({ citeKey, reference }: { citeKey: string; reference?: Reference }) {
  if (!reference) {
    return <span className="cite cite--missing">[@{citeKey}]</span>;
  }
  const label = `${reference.title}${reference.year ? ` (${reference.year})` : ""}`;
  return (
    <a className="cite" href={`#${refId(citeKey)}`} title={label} aria-label={`Reference ${citeKey}: ${label}`}>
      [{citeKey}]
    </a>
  );
}

/** Renders the Writer's FinalReview (backend/app/schemas/contracts/review.py) as a document. */
export function ReviewDocument({ review }: { review: FinalReview }) {
  const references = new Map(review.references.map((r) => [r.citation_key, r]));
  const cite = (key: string) => <Citation citeKey={key} reference={references.get(key)} />;
  const status = EVIDENCE_STATUS[review.evidence_status];

  return (
    <article className="review">
      <header className="review__head">
        <p className="eyebrow">Literature review</p>
        <h2 className="review__title">{review.title}</h2>
        <div className="review__status">
          <ToneBadge tone={status.tone}>{status.label}</ToneBadge>
          <span className="small muted">{status.meaning}</span>
        </div>
      </header>

      <section className="review__abstract" aria-label="Abstract">
        <h3 className="review__label">Abstract</h3>
        <Markdown source={review.abstract} cite={cite} />
      </section>

      {review.limitations.length ? (
        <section className={`review__limitations tone-${status.tone === "positive" ? "neutral" : status.tone}`} aria-labelledby="review-limitations">
          <h3 id="review-limitations" className="review__label">
            Limitations
          </h3>
          <ul>
            {review.limitations.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="review__body">
        {review.sections.map((section, i) => (
          <section key={i} className="review__section" aria-labelledby={`section-${i}`}>
            <h3 id={`section-${i}`} className="review__h">
              <span className="review__h-num" aria-hidden="true">
                {i + 1}
              </span>
              {section.heading}
            </h3>
            <div className="prose">
              <Markdown source={section.body_markdown} cite={cite} />
            </div>
          </section>
        ))}
      </div>

      <section className="references" aria-labelledby="references-title">
        <h3 id="references-title" className="review__h">
          References
        </h3>
        {review.references.length ? (
          <ol className="references__list">
            {review.references.map((ref) => (
              <li key={ref.citation_key} id={refId(ref.citation_key)} className="references__item">
                <span className="references__key mono">{ref.citation_key}</span>
                <span className="references__text">
                  {formatAuthors(ref.authors)}
                  {ref.year ? ` (${ref.year}). ` : ". "}
                  <cite className="references__title">{ref.title}</cite>
                  {/[.?!]$/.test(ref.title) ? "" : "."}
                  {ref.doi ? (
                    <>
                      {" "}
                      <a
                        className="text-link references__doi break"
                        href={`https://doi.org/${ref.doi.replace(/^https?:\/\/(dx\.)?doi\.org\//, "")}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        doi:{ref.doi.replace(/^https?:\/\/(dx\.)?doi\.org\//, "")}
                      </a>
                    </>
                  ) : null}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">The review cites no papers.</p>
        )}
      </section>
    </article>
  );
}
