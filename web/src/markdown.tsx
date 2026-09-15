import { type ReactNode } from "react";

/* Lightweight zero-dependency Markdown renderer for assistant replies.
 * Supports: fenced code, headings, bold/italic/strikethrough, inline code,
 * links, unordered/ordered lists, blockquotes, horizontal rules. */

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let rest = text;
  let key = 0;
  // Combined pattern: code spans, bold, italic, strike, links.
  const pattern =
    /`([^`]+)`|\*\*([^*]+)\*\*|__([^_]+)__|\*([^*]+)\*|_([^_]+)_|~~([^~]+)~~|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let match: RegExpExecArray | null;
  let plain = "";
  while ((match = pattern.exec(rest)) !== null) {
    plain += rest.slice(0, match.index);
    const mk = `${keyPrefix}-${key++}`;
    if (match[1] !== undefined) {
      if (plain) nodes.push(plain);
      plain = "";
      nodes.push(
        <code className="md-code" key={mk}>
          {match[1]}
        </code>,
      );
    } else if (match[2] !== undefined || match[3] !== undefined) {
      if (plain) nodes.push(plain);
      plain = "";
      nodes.push(<strong key={mk}>{match[2] ?? match[3]}</strong>);
    } else if (match[6] !== undefined) {
      if (plain) nodes.push(plain);
      plain = "";
      nodes.push(<s key={mk}>{match[6]}</s>);
    } else if (match[4] !== undefined || match[5] !== undefined) {
      if (plain) nodes.push(plain);
      plain = "";
      nodes.push(<em key={mk}>{match[4] ?? match[5]}</em>);
    } else if (match[7] !== undefined && match[8] !== undefined) {
      if (plain) nodes.push(plain);
      plain = "";
      nodes.push(
        <a href={match[8]} key={mk} rel="noreferrer" target="_blank">
          {match[7]}
        </a>,
      );
    }
    rest = rest.slice(match.index + match[0].length);
    pattern.lastIndex = 0;
  }
  if (plain + rest) nodes.push(plain + rest);
  return nodes;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // fenced code block
    const fence = line.match(/^\s*```(\w*)\s*$/);
    if (fence) {
      const buf: string[] = [];
      i += 1;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        buf.push(lines[i]);
        i += 1;
      }
      i += 1; // closing fence
      blocks.push(
        <pre className="code-block md-fence" key={`fence-${key++}`}>
          {buf.join("\n") || " "}
        </pre>,
      );
      continue;
    }

    // heading
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      const cls = `md-h${level}`;
      blocks.push(
        <div className={cls} key={`h-${key++}`}>
          {renderInline(heading[2], `h${key}`)}
        </div>,
      );
      i += 1;
      continue;
    }

    // horizontal rule
    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) {
      blocks.push(<hr className="md-hr" key={`hr-${key++}`} />);
      i += 1;
      continue;
    }

    // blockquote
    if (/^\s*>\s?/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ""));
        i += 1;
      }
      blocks.push(
        <blockquote className="md-quote" key={`q-${key++}`}>
          {renderInline(buf.join("\n"), `q${key}`)}
        </blockquote>,
      );
      continue;
    }

    // unordered list
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ul className="md-list" key={`ul-${key++}`}>
          {items.map((item, idx) => (
            <li key={idx}>{renderInline(item, `ul${key}-${idx}`)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    // ordered list
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ol className="md-list md-ol" key={`ol-${key++}`}>
          {items.map((item, idx) => (
            <li key={idx}>{renderInline(item, `ol${key}-${idx}`)}</li>
          ))}
        </ol>,
      );
      continue;
    }

    // blank line
    if (!line.trim()) {
      i += 1;
      continue;
    }

    // paragraph (merge consecutive non-empty plain lines)
    const buf: string[] = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*(#{1,4}\s|```|[-*+]\s|\d+[.)]\s|>\s?|---+\s*$)/.test(lines[i])
    ) {
      buf.push(lines[i]);
      i += 1;
    }
    blocks.push(
      <p className="md-p" key={`p-${key++}`}>
        {renderInline(buf.join("\n"), `p${key}`)}
      </p>,
    );
  }

  return <div className="md">{blocks}</div>;
}
