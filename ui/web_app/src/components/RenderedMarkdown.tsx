import { useCallback, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";

import { type PrismStyleMap, withTransparentPrismTheme } from "@sovara/shared-components/utils/prismTheme";

type MarkdownCodeProps = {
  children?: ReactNode;
  className?: string;
};

const LANG_DISPLAY: Record<string, string> = {
  sql: "SQL",
  json: "JSON",
  python: "Python",
  rust: "Rust",
  javascript: "JavaScript",
  typescript: "TypeScript",
  tsx: "TSX",
  go: "Go",
  html: "HTML",
  bash: "Bash",
  css: "CSS",
  yaml: "YAML",
  xml: "XML",
  text: "Text",
};

const syntaxTheme = withTransparentPrismTheme(oneLight as unknown as PrismStyleMap, {
  fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace',
  fontSize: "12.5px",
  lineHeight: "1.6",
});

function normalizeLanguage(language: string | undefined): string | null {
  if (!language) return null;
  const normalized = language.trim().toLowerCase();
  if (!normalized) return null;
  if (normalized === "js") return "javascript";
  if (normalized === "ts") return "typescript";
  return normalized;
}

function inferCodeLanguage(value: string): string {
  const trimmed = value.trim();

  if (/^\s*SELECT\b[\s\S]*\bFROM\b/i.test(trimmed) || /\bGROUP BY\b/i.test(trimmed)) {
    return "sql";
  }

  if (/^\s*(def |class |from |import )/m.test(trimmed) || /\bprint\(/.test(trimmed)) {
    return "python";
  }

  if (/^\s*(const |let |function |import |export )/m.test(trimmed) || /=>/.test(trimmed)) {
    return "javascript";
  }

  if (/^\s*[{[][\s\S]*[}\]]\s*$/.test(trimmed)) {
    return "json";
  }

  if (/^\s*<[\s\S]+>\s*$/.test(trimmed)) {
    return "xml";
  }

  return "text";
}

function MarkdownCodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [code]);

  return (
    <div className="code-block">
      <div className="code-block-header">
        <span className="code-block-lang">{LANG_DISPLAY[language] ?? language}</span>
        <div className="code-block-actions">
          <button
            className="code-block-copy"
            onClick={(event) => {
              event.stopPropagation();
              handleCopy();
            }}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
      <SyntaxHighlighter
        language={language}
        style={syntaxTheme}
        customStyle={{
          padding: "12px 14px",
          borderRadius: 0,
          background: "transparent",
          fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace',
          fontSize: "12.5px",
          lineHeight: "1.6",
        }}
        codeTagProps={{ style: { background: "transparent" } }}
        wrapLongLines
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}

export function RenderedMarkdown({ markdown, className }: { markdown: string; className?: string }) {
  return (
    <div className={className}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          code(props: MarkdownCodeProps) {
            const text = String(props.children ?? "").replace(/\n$/, "");
            const languageMatch = /language-([\w+-]+)/.exec(props.className || "");
            const isBlock = Boolean(languageMatch) || text.includes("\n");

            if (!isBlock) {
              return <code className="io-inline-code">{props.children}</code>;
            }

            return <MarkdownCodeBlock code={text} language={normalizeLanguage(languageMatch?.[1]) ?? inferCodeLanguage(text)} />;
          },
        }}
      >
        {markdown}
      </Markdown>
    </div>
  );
}
