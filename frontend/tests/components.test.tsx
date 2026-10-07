import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Timeline } from "@/components/agents/Timeline";
import { ReviewDocument } from "@/components/results/ReviewDocument";
import { RunList } from "@/components/runs/RunList";
import { RunStatusBanner } from "@/components/runs/RunStatusBanner";
import { CredentialCard, maskedKey } from "@/components/settings/CredentialCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { RUN_STATUSES, type CredentialStatus } from "@/lib/api/types";
import { readOutputs } from "@/lib/runs/outputs";
import { deriveTimeline } from "@/lib/trace/timeline";
import { realRun, runDetail } from "./fixtures";

const text = (markup: string) => markup.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
const noop = () => undefined;

describe("adaptive timeline (real run)", () => {
  const { events, outputs } = realRun();
  const markup = renderToStaticMarkup(
    <Timeline timeline={deriveTimeline(events, true)} live={false} subQuestions={readOutputs(outputs).subQuestions} />,
  );
  const plain = text(markup);

  test("shows both iterations and each agent in the order it ran", () => {
    assert.equal((markup.match(/class="tl-iter"/g) ?? []).length, 2);
    const order = [...markup.matchAll(/data-node="([a-z_]+)"/g)].map((m) => m[1]);
    assert.deepEqual(order, [
      "planner",
      "literature_search",
      "document_analysis",
      "evidence_synthesis",
      "replanning",
      "literature_search",
      "document_analysis",
      "evidence_synthesis",
      "review_writer",
    ]);
  });

  test("makes the verdicts, the replanning and the limit visible", () => {
    assert.equal((plain.match(/Evidence insufficient/g) ?? []).length, 2);
    assert.match(plain, /Adaptive replanning Search revision → back to Literature Search · iteration 2/);
    assert.match(plain, /What is the average change in systolic blood pressure/); // reason linked to its sub-question
    assert.match(plain, /Limit reached Stopped because the LLM call budget could not cover another research iteration/);
    assert.match(plain, /Run completed with limitations after 2 iteration\(s\)/);
  });

  test("a live run with no events yet explains what will appear", () => {
    const empty = text(renderToStaticMarkup(<Timeline timeline={deriveTimeline([], false)} live />));
    assert.match(empty, /Waiting for the first agent/);
  });
});

describe("completed with limitations", () => {
  const { run, events, result } = realRun();
  const timeline = deriveTimeline(events, true);

  test("the banner states the limit and the review's limitations up front", () => {
    const plain = text(renderToStaticMarkup(<RunStatusBanner run={run} result={result} timeline={timeline} onOpen={noop} />));
    assert.match(plain, /Review written with limitations · Evidence limited/);
    assert.match(plain, /LLM call budget/);
    assert.ok(result.review!.limitations.length > 0);
    assert.ok(plain.includes(result.review!.limitations[0]));
  });

  test("the review renders sections, resolvable citations and every reference", () => {
    const review = result.review!;
    const markup = renderToStaticMarkup(<ReviewDocument review={review} />);
    assert.ok(text(markup).includes(review.title));
    for (const section of review.sections) assert.ok(markup.includes(section.heading.replace(/&/g, "&amp;")));
    for (const ref of review.references) {
      assert.match(markup, new RegExp(`id="ref-${ref.citation_key}"`));
    }
    const cited = new Set(review.sections.flatMap((s) => s.citation_keys));
    for (const key of cited) assert.match(markup, new RegExp(`href="#ref-${key}"`));
    assert.doesNotMatch(markup, /cite--missing/);
    assert.match(text(markup), /Evidence limited/);
    assert.match(text(markup), /Limitations/);
  });

  test("a failed run explains the error without internals", () => {
    const failed = runDetail({
      status: "failed",
      error: { code: "no_provider_configured", message: "No LLM provider is configured", node: "planner" },
    });
    const plain = text(
      renderToStaticMarkup(<RunStatusBanner run={failed} result={null} timeline={deriveTimeline([], true)} onOpen={noop} />),
    );
    assert.match(plain, /Failed during planner/);
    assert.match(plain, /Add a Groq or Gemini key in Settings/);
  });
});

describe("history and status", () => {
  test("an empty history invites the first question", () => {
    const markup = renderToStaticMarkup(<RunList runs={[]} />);
    assert.match(text(markup), /No research yet/);
    assert.match(markup, /href="\/research"/);
  });

  test("runs link to their detail page with a text status", () => {
    const { run } = realRun();
    const markup = renderToStaticMarkup(<RunList runs={[run]} />);
    assert.match(markup, new RegExp(`href="/runs/${run.id}"`));
    assert.match(text(markup), /Completed with limitations/);
  });

  test("every status has a text label, not only a colour", () => {
    for (const status of RUN_STATUSES) {
      const plain = text(renderToStaticMarkup(<StatusBadge status={status} />)).trim();
      assert.ok(plain.length > 3, status);
    }
  });
});

describe("credential settings", () => {
  const stored: CredentialStatus = {
    provider: "groq",
    configured: true,
    key_hint: "x9Qa",
    status: "valid",
    validated_at: "2026-10-07T12:00:00Z",
    updated_at: "2026-10-07T12:00:00Z",
  };
  const save = async () => stored;
  const remove = async () => undefined;

  test("a stored key is only ever shown masked, with its last four characters", () => {
    const markup = renderToStaticMarkup(<CredentialCard credential={stored} onSave={save} onDelete={remove} />);
    assert.ok(markup.includes(maskedKey("x9Qa")));
    assert.match(text(markup), /Verified/);
    assert.doesNotMatch(markup, /<input/); // no key field until the user chooses to replace it
  });

  test("the key field is a password input that starts empty", () => {
    const missing: CredentialStatus = { ...stored, provider: "gemini", configured: false, key_hint: null, status: null };
    const markup = renderToStaticMarkup(<CredentialCard credential={missing} onSave={save} onDelete={remove} />);
    const input = markup.match(/<input[^>]*>/)?.[0] ?? "";
    assert.match(input, /type="password"/);
    assert.match(input, /autoComplete="off"|autocomplete="off"/);
    assert.match(input, /value=""/);
    assert.match(text(markup), /Not added/);
  });
});
