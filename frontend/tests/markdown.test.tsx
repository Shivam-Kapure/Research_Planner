import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Markdown, parseBlocks } from "@/lib/markdown";

const cite = (key: string) => <a href={`#ref-${key}`}>[{key}]</a>;
const html = (source: string) => renderToStaticMarkup(<Markdown source={source} cite={cite} />);

describe("Markdown", () => {
  test("renders paragraphs, emphasis, lists and adjacent citations", () => {
    const out = html(
      "Aerobic exercise lowers **systolic** pressure [@P4][@P5].\n\n- first point [@P1]\n- *second* point\n\n1. one\n2. two",
    );
    assert.match(out, /<p>Aerobic exercise lowers <strong>systolic<\/strong> pressure <a href="#ref-P4">\[P4\]<\/a><a href="#ref-P5">\[P5\]<\/a>\.<\/p>/);
    assert.match(out, /<ul><li>first point <a href="#ref-P1">\[P1\]<\/a><\/li><li><em>second<\/em> point<\/li><\/ul>/);
    assert.match(out, /<ol><li>one<\/li><li>two<\/li><\/ol>/);
  });

  test("never turns model output into markup", () => {
    const out = html('<script>alert(1)</script> <img src=x onerror="alert(2)"> [click](javascript:alert(3))');
    assert.doesNotMatch(out, /<script|<img|href="javascript/);
    assert.match(out, /&lt;script&gt;/);
  });

  test("links only http(s) URLs, with safe rel attributes", () => {
    const out = html("See [the trial](https://example.org/trial).");
    assert.match(out, /<a href="https:\/\/example.org\/trial" rel="noopener noreferrer nofollow" target="_blank">the trial<\/a>/);
  });

  test("keeps headings below the section heading and joins wrapped lines", () => {
    const blocks = parseBlocks("## Methods\nline one\nline two\n> quoted");
    assert.deepEqual(blocks, [
      { type: "heading", level: 2, text: "Methods" },
      { type: "paragraph", text: "line one line two" },
      { type: "quote", text: "quoted" },
    ]);
    assert.match(html("## Methods"), /^<h4>Methods<\/h4>$/);
  });

  test("does not italicise inside snake_case identifiers", () => {
    assert.equal(html("a sub_question_id value"), "<p>a sub_question_id value</p>");
  });
});
