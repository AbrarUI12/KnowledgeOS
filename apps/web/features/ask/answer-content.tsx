"use client";

import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import type { components } from "@knowledgeos/contracts";

type Node = { type: string; value?: string; children?: Node[]; url?: string };
function citationMarkers() {
  return (tree: Node) => {
    function visit(node: Node) {
      if (!node.children || ["link", "code", "inlineCode"].includes(node.type)) return;
      node.children = node.children.flatMap((child): Node[] => {
        if (child.type !== "text" || !child.value) {
          visit(child);
          return [child];
        }
        return child.value
          .replace(/\[(S[1-9][0-9]*(?:,\s*S[1-9][0-9]*)+)\]/g, (_, aliases: string) =>
            aliases
              .split(/,\s*/)
              .map((alias) => `[${alias}]`)
              .join(" "),
          )
          .split(/(\[S[1-9][0-9]*\])/g)
          .filter(Boolean)
          .map((text) =>
            /^\[S[1-9][0-9]*\]$/.test(text)
              ? {
                  type: "link",
                  url: `#citation-${text.slice(1, -1)}`,
                  children: [{ type: "text", value: text }],
                }
              : { type: "text", value: text },
          );
      });
    }
    visit(tree);
  };
}

export function AnswerContent({
  text,
  sources,
  citations,
  onInspect,
}: {
  text: string;
  sources: components["schemas"]["SourceAlias"][];
  citations: Record<string, boolean>;
  onInspect: (source: components["schemas"]["SourceAlias"]) => void;
}) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm, citationMarkers]}
      rehypePlugins={[rehypeSanitize]}
      skipHtml
      components={{
        a: ({ href, children }) => {
          const alias = href?.match(/^#citation-(S[1-9][0-9]*)$/)?.[1];
          const source = sources.find((item) => item.alias === alias);
          return alias && source && citations[alias] !== false ? (
            <button
              className="rounded-control bg-accent-soft px-1 text-accent"
              aria-label={`Inspect source ${alias}`}
              onClick={() => onInspect(source)}
            >
              {children}
            </button>
          ) : (
            <span>{children}</span>
          );
        },
        img: () => null,
        p: ({ children }) => <p className="mb-4 last:mb-0">{children}</p>,
        table: ({ children }) => (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">{children}</table>
          </div>
        ),
        th: ({ children }) => (
          <th className="border border-line bg-surface-2 p-2 text-left">{children}</th>
        ),
        td: ({ children }) => <td className="border border-line p-2">{children}</td>,
      }}
    >
      {text}
    </Markdown>
  );
}
