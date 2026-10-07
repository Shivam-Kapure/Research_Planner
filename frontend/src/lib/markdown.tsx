import { Fragment, type ReactNode } from "react";

// A deliberately small Markdown renderer for review sections written by the LLM. It builds
// React elements (never HTML strings), so model output cannot inject markup or scripts.
// Supported: paragraphs, headings, bullet and numbered lists, block quotes, **bold**,
// *italic*, `code`, http(s) links and [@KEY] citations (backend/app/schemas/contracts/review.py).

export type CitationRenderer = (key: string, index: number) => ReactNode;

const INLINE =
  /\[@([A-Za-z0-9_:-]{1,64})\]|\*\*(.+?)\*\*|__(.+?)__|\*(?!\s)(.+?)\*|_(?!\s)(.+?)_(?![A-Za-z0-9])|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;

export function renderInline(text: string, cite: CitationRenderer, keyPrefix = "i"): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let n = 0;
  for (const match of text.matchAll(INLINE)) {
    const start = match.index ?? 0;
    if (start > last) nodes.push(text.slice(last, start));
    const key = `${keyPrefix}-${n++}`;
    const [, citation, bold1, bold2, em1, em2, code, linkText, href] = match;
    if (citation) nodes.push(<Fragment key={key}>{cite(citation, n)}</Fragment>);
    else if (bold1 ?? bold2) nodes.push(<strong key={key}>{renderInline(bold1 ?? bold2, cite, key)}</strong>);
    else if (em1 ?? em2) nodes.push(<em key={key}>{renderInline(em1 ?? em2, cite, key)}</em>);
    else if (code) nodes.push(<code key={key}>{code}</code>);
    else if (linkText && href) {
      nodes.push(
        <a key={key} href={href} rel="noopener noreferrer nofollow" target="_blank">
          {linkText}
        </a>,
      );
    }
    last = start + match[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

type Block =
  | { type: "heading"; level: number; text: string }
  | { type: "paragraph"; text: string }
  | { type: "quote"; text: string }
  | { type: "list"; ordered: boolean; items: string[] };

const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;

export function parseBlocks(markdown: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let quote: string[] = [];

  const flush = () => {
    if (paragraph.length) blocks.push({ type: "paragraph", text: paragraph.join(" ") });
    if (list) blocks.push({ type: "list", ...list });
    if (quote.length) blocks.push({ type: "quote", text: quote.join(" ") });
    paragraph = [];
    list = null;
    quote = [];
  };

  for (const raw of markdown.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flush();
      continue;
    }
    const heading = /^\s*(#{1,6})\s+(.*)$/.exec(line);
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    const quoted = /^\s*>\s?(.*)$/.exec(line);
    if (heading) {
      flush();
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2] });
    } else if (bullet || numbered) {
      const ordered = !bullet;
      if (paragraph.length || quote.length || (list && list.ordered !== ordered)) flush();
      list ??= { ordered, items: [] };
      list.items.push((bullet ?? numbered)![1]);
    } else if (quoted) {
      if (paragraph.length || list) flush();
      quote.push(quoted[1]);
    } else if (list && /^\s{2,}/.test(raw)) {
      list.items[list.items.length - 1] += ` ${line.trim()}`; // continuation of a list item
    } else {
      if (list || quote.length) flush();
      paragraph.push(line.trim());
    }
  }
  flush();
  return blocks;
}

/** Renders section Markdown. Headings inside a section start at <h4>, below the section's <h3>. */
export function Markdown({ source, cite }: { source: string; cite: CitationRenderer }) {
  return (
    <>
      {parseBlocks(source).map((block, i) => {
        const key = `b${i}`;
        switch (block.type) {
          case "heading": {
            const Tag = block.level <= 2 ? "h4" : "h5";
            return <Tag key={key}>{renderInline(block.text, cite, key)}</Tag>;
          }
          case "quote":
            return <blockquote key={key}>{renderInline(block.text, cite, key)}</blockquote>;
          case "list": {
            const Tag = block.ordered ? "ol" : "ul";
            return (
              <Tag key={key}>
                {block.items.map((item, j) => (
                  <li key={j}>{renderInline(item, cite, `${key}-${j}`)}</li>
                ))}
              </Tag>
            );
          }
          default:
            return <p key={key}>{renderInline(block.text, cite, key)}</p>;
        }
      })}
    </>
  );
}
