import { useState, useCallback, useMemo, useRef } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AttachmentStrip } from "./AttachmentPreview";
import { extractAttachments } from "../attachmentUtils";
import { Sparkles, Pencil, Loader2, Copy, ChevronDown, ChevronRight, Braces } from "lucide-react";
import {
  detectDocument,
  formatFileSize,
  getFileExtension,
  type DetectedDocument,
} from "@sovara/shared-components/utils/documentDetection";
import type { EditKey, GraphEdge, GraphNode } from "../hooks/useRunSessionState";

function topoSortNodes(graphNodes: GraphNode[], graphEdges: GraphEdge[]): GraphNode[] {
  const inDeg = new Map<string, number>();
  const children = new Map<string, string[]>();
  for (const node of graphNodes) {
    inDeg.set(node.id, 0);
    children.set(node.id, []);
  }
  for (const edge of graphEdges) {
    inDeg.set(edge.target, (inDeg.get(edge.target) ?? 0) + 1);
    children.get(edge.source)?.push(edge.target);
  }

  const queue = graphNodes.filter((node) => (inDeg.get(node.id) ?? 0) === 0).map((node) => node.id);
  const order: string[] = [];
  let index = 0;
  while (index < queue.length) {
    const id = queue[index++];
    order.push(id);
    for (const childId of children.get(id) ?? []) {
      inDeg.set(childId, (inDeg.get(childId) ?? 0) - 1);
      if (inDeg.get(childId) === 0) queue.push(childId);
    }
  }

  const idToNode = new Map(graphNodes.map((node) => [node.id, node]));
  return order.map((id) => idToNode.get(id)!).filter(Boolean);
}

const syntaxTheme: Record<string, React.CSSProperties> = {
  ...oneLight,
  'pre[class*="language-"]': {
    ...(oneLight['pre[class*="language-"]'] || {}),
    background: "transparent",
    margin: 0,
    padding: 0,
    textShadow: "none",
  },
  'code[class*="language-"]': {
    ...(oneLight['code[class*="language-"]'] || {}),
    background: "transparent",
    fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace',
    fontSize: "12.5px",
    lineHeight: "1.6",
    textShadow: "none",
  },
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

const MAX_PRETTY_DEPTH = 4;
const FENCED_CODE_RE = /^```([a-zA-Z0-9_+-]+)?\n([\s\S]*?)\n```$/;
const XML_RE = /^<([A-Za-z_][\w:.-]*)(\s+[^<>]*)?>[\s\S]*<\/\1>$|^<([A-Za-z_][\w:.-]*)(\s+[^<>]*)?\/>$/;
const STRONG_MARKDOWN_PATTERNS = [
  /^#{1,6}\s/m,
  /^[-*+]\s/m,
  /^\d+\.\s/m,
  /^>\s/m,
  /\|.+\|/,
  /\[[^\]]+\]\([^)]+\)/,
  /```[\s\S]*```/,
];

type StringClassification =
  | { kind: "json"; parsed: unknown; label: "json object" | "json list" }
  | { kind: "markdown" }
  | { kind: "code"; language: string; fenced: boolean }
  | { kind: "xml" }
  | { kind: "plain" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isScalarValue(value: unknown): boolean {
  return value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function getScalarTypeLabel(value: unknown): "null" | "string" | "int" | "float" | "boolean" {
  if (value === null) return "null";
  if (typeof value === "string") return "string";
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return Number.isInteger(value) ? "int" : "float";
  return "string";
}

function normalizeLanguage(language: string | undefined): string | null {
  if (!language) return null;
  const normalized = language.trim().toLowerCase();
  if (!normalized) return null;
  if (normalized === "js") return "javascript";
  if (normalized === "ts") return "typescript";
  return normalized;
}

function looksLikeXml(value: string): boolean {
  return XML_RE.test(value);
}

function looksLikeMarkdown(value: string): boolean {
  if (STRONG_MARKDOWN_PATTERNS.some((pattern) => pattern.test(value))) {
    return true;
  }

  const inlineCodeMatches = value.match(/`[^`\n]+`/g) || [];
  return inlineCodeMatches.length >= 2 && value.includes("\n");
}

function inferCodeLanguage(value: string): string {
  const trimmed = value.trim();

  if (/^\s*SELECT\b[\s\S]*\bFROM\b/i.test(trimmed) || /\bGROUP BY\b/i.test(trimmed)) {
    return "sql";
  }

  if (/^\s*(def |from |import )/m.test(trimmed) || /\blambda\b/.test(trimmed)) {
    return "python";
  }

  if (/^\s*package\s+\w+/m.test(trimmed) && /\bfunc\s+\w+\(/.test(trimmed)) {
    return "go";
  }

  if (/^\s*#\!\/bin\/(ba)?sh/m.test(trimmed) || /(^|\n)\s*(echo|export|cd|grep|uv|python3?)\b/.test(trimmed)) {
    return "bash";
  }

  if (/<[A-Za-z]/.test(trimmed) && /\{[^}]*[:=][^}]*\}/.test(trimmed)) {
    return "tsx";
  }

  if (/\binterface\s+\w+/.test(trimmed) || /\btype\s+\w+\s*=/.test(trimmed) || /\bexport\s+function\b/.test(trimmed)) {
    return "typescript";
  }

  if (/\bfunction\b/.test(trimmed) || /\bconsole\./.test(trimmed) || /=>/.test(trimmed)) {
    return "javascript";
  }

  if (looksLikeXml(trimmed)) {
    return "xml";
  }

  return "text";
}

function inferUnfencedCodeLanguage(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed.includes("\n") && trimmed.length < 24) {
    return null;
  }

  const language = inferCodeLanguage(trimmed);
  if (language === "text") {
    return null;
  }

  const looksCodeLike =
    /[{}();=]/.test(trimmed) ||
    /\b(function|class|def|import|export|return|SELECT|FROM|WHERE|package|func)\b/.test(trimmed);

  return looksCodeLike ? language : null;
}

function classifyStringContent(value: string): StringClassification {
  const trimmed = value.trim();
  if (!trimmed) {
    return { kind: "plain" };
  }

  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      if (Array.isArray(parsed)) {
        return { kind: "json", parsed, label: "json list" };
      }
      if (isRecord(parsed)) {
        return { kind: "json", parsed, label: "json object" };
      }
    } catch {
      // Fall through to the next classifier.
    }
  }

  const fenced = trimmed.match(FENCED_CODE_RE);
  if (fenced) {
    return {
      kind: "code",
      language: normalizeLanguage(fenced[1]) || inferCodeLanguage(fenced[2]),
      fenced: true,
    };
  }

  if (looksLikeXml(trimmed)) {
    return { kind: "xml" };
  }

  if (looksLikeMarkdown(value)) {
    return { kind: "markdown" };
  }

  const inferredLanguage = inferUnfencedCodeLanguage(value);
  if (inferredLanguage) {
    return { kind: "code", language: inferredLanguage, fenced: false };
  }

  return { kind: "plain" };
}

function unwrapFencedCode(value: string): { language: string; code: string } | null {
  const match = value.trim().match(FENCED_CODE_RE);
  if (!match) {
    return null;
  }

  return {
    language: normalizeLanguage(match[1]) || inferCodeLanguage(match[2]),
    code: match[2],
  };
}

function shouldCollapseLongText(value: string): boolean {
  return value.length > 360 || value.split("\n").length > 10;
}

function getStringPreview(value: string, maxLength = 180): string {
  if (value.length <= maxLength) {
    return value;
  }

  return `${value.slice(0, maxLength).trimEnd()}…`;
}

function getUniformObjectArrayColumns(value: unknown[]): string[] | null {
  if (value.length === 0 || !value.every((item) => isRecord(item))) {
    return null;
  }

  const firstColumns = Object.keys(value[0] as Record<string, unknown>);
  if (firstColumns.length === 0 || firstColumns.length > 8) {
    return null;
  }

  const signature = firstColumns.join("\u0000");
  for (const item of value as Record<string, unknown>[]) {
    if (Object.keys(item).join("\u0000") !== signature) {
      return null;
    }
    for (const key of firstColumns) {
      const cell = item[key];
      if (!isScalarValue(cell)) {
        return null;
      }

      if (typeof cell === "string") {
        if (detectDocument(cell, item) || shouldCollapseLongText(cell)) {
          return null;
        }

        if (classifyStringContent(cell).kind !== "plain") {
          return null;
        }
      }
    }
  }

  return firstColumns;
}

function stringifyScalar(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function CodeBlock({ code, language }: { code: string; language: string }) {
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
        <button className="code-block-copy" onClick={handleCopy}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <SyntaxHighlighter
        language={language}
        style={syntaxTheme}
        customStyle={{
          margin: 0,
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

function PrettyBadge({ label }: { label: string }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "1px 6px",
        borderRadius: "999px",
        background: "rgba(138, 138, 126, 0.06)",
        border: "1px solid rgba(138, 138, 126, 0.14)",
        fontSize: "9.5px",
        fontWeight: 500,
        color: "var(--color-text-muted)",
      }}
    >
      {label}
    </span>
  );
}

function RawToggleIconButton({
  showingRaw,
  onClick,
}: {
  showingRaw: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={showingRaw ? "Show rendered" : "Show raw"}
      aria-label={showingRaw ? "Show rendered" : "Show raw"}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "20px",
        height: "20px",
        borderRadius: "999px",
        border: showingRaw ? "1px solid rgba(67, 136, 78, 0.24)" : "1px solid rgba(138, 138, 126, 0.14)",
        background: showingRaw ? "rgba(67, 136, 78, 0.08)" : "rgba(138, 138, 126, 0.04)",
        color: showingRaw ? "#43884e" : "var(--color-text-muted)",
        cursor: "pointer",
        padding: 0,
      }}
    >
      <Braces size={12} />
    </button>
  );
}

function ChevronToggleButton({
  expanded,
  onClick,
  title,
}: {
  expanded: boolean;
  onClick: () => void;
  title: string;
}) {
  const Icon = expanded ? ChevronDown : ChevronRight;
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "20px",
        height: "20px",
        borderRadius: "999px",
        border: "1px solid rgba(138, 138, 126, 0.14)",
        background: "rgba(138, 138, 126, 0.04)",
        color: "var(--color-text-muted)",
        cursor: "pointer",
        padding: 0,
      }}
    >
      <Icon size={13} />
    </button>
  );
}

function PrettyCard({
  label,
  badge,
  actions,
  depth,
  compact = false,
  children,
}: {
  label: string | null;
  badge?: string;
  actions?: React.ReactNode;
  depth: number;
  compact?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: "10px", marginLeft: depth > 0 ? "12px" : 0 }}>
      {(label || badge || actions) && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "8px",
            marginBottom: "6px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0 }}>
            {label && (
              <span
                style={{
                  color: "var(--color-text)",
                  fontSize: "13px",
                  fontWeight: 600,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {label}
              </span>
            )}
            {badge && <PrettyBadge label={badge} />}
          </div>
          {actions}
        </div>
      )}
      <div
        style={{
          border: "1px solid var(--color-border)",
          borderRadius: "10px",
          background: "rgba(255,255,255,0.42)",
          padding: compact ? "8px 10px" : "12px",
        }}
      >
        {children}
      </div>
    </div>
  );
}

function CompactScalarValue({
  value,
}: {
  value: unknown;
}) {
  const scalarText = stringifyScalar(value);
  const color =
    value === null
      ? "#8a8a7e"
      : typeof value === "boolean"
        ? "#b45309"
        : typeof value === "number"
          ? "#b45309"
          : "#43884e";

  return (
    <div
      style={{
        minWidth: 0,
        fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace',
        fontSize: "12.5px",
        lineHeight: "1.5",
        color,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      {scalarText}
    </div>
  );
}

function ScalarBox({ label, value, depth }: { label: string | null; value: unknown; depth: number }) {
  return (
    <PrettyCard label={label} badge={getScalarTypeLabel(value)} depth={depth} compact>
      <CompactScalarValue value={value} />
    </PrettyCard>
  );
}

function isInlineSimpleValue(value: unknown, siblingData?: Record<string, unknown>): boolean {
  if (value === null || typeof value === "number" || typeof value === "boolean") {
    return true;
  }

  if (typeof value !== "string") {
    return false;
  }

  if (detectDocument(value, siblingData)) {
    return false;
  }

  if (shouldCollapseLongText(value)) {
    return false;
  }

  return classifyStringContent(value).kind === "plain";
}

function InlineValueRow({
  label,
  value,
}: {
  label: string;
  value: unknown;
}) {
  const isString = typeof value === "string";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "10px",
        padding: "8px 10px",
        borderRadius: "8px",
        border: "1px solid rgba(138, 138, 126, 0.14)",
        background: "rgba(255,255,255,0.26)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: "140px", maxWidth: "240px" }}>
        <span
          style={{
            color: "var(--color-text)",
            fontSize: "13px",
            fontWeight: 600,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {label}
        </span>
        <PrettyBadge label={getScalarTypeLabel(value)} />
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        {isString ? (
          <div
            style={{
              fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace',
              fontSize: "12.5px",
              lineHeight: "1.5",
              color: "#43884e",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {value}
          </div>
        ) : (
          <CompactScalarValue value={value} />
        )}
      </div>
    </div>
  );
}

function ArrayIndexLabel({ index }: { index: number }) {
  return (
    <span
      style={{
        display: "inline-block",
        minWidth: "16px",
        fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace',
        fontSize: "11px",
        lineHeight: 1,
        color: "var(--color-text-muted)",
        opacity: 0.7,
        textAlign: "right",
      }}
    >
      {index}
    </span>
  );
}

function ArrayItemBox({
  index,
  children,
}: {
  index: number;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        border: "1px solid rgba(138, 138, 126, 0.14)",
        borderRadius: "8px",
        background: "rgba(255,255,255,0.26)",
        padding: "8px 10px",
      }}
    >
      <div style={{ marginBottom: "6px" }}>
        <ArrayIndexLabel index={index} />
      </div>
      {children}
    </div>
  );
}

function InlineArrayItemRow({
  index,
  value,
}: {
  index: number;
  value: unknown;
}) {
  const isString = typeof value === "string";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "10px",
        padding: "8px 10px",
        borderRadius: "8px",
        border: "1px solid rgba(138, 138, 126, 0.14)",
        background: "rgba(255,255,255,0.26)",
      }}
    >
      <ArrayIndexLabel index={index} />
      <div style={{ minWidth: 0, flex: 1 }}>
        {isString ? (
          <div
            style={{
              fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace',
              fontSize: "12.5px",
              lineHeight: "1.5",
              color: "#43884e",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {value}
          </div>
        ) : (
          <CompactScalarValue value={value} />
        )}
      </div>
    </div>
  );
}

function MarkdownContent({ markdown }: { markdown: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        code(props: any) {
          const text = String(props.children ?? "").replace(/\n$/, "");
          const languageMatch = /language-([\w+-]+)/.exec(props.className || "");
          const isBlock = Boolean(languageMatch) || text.includes("\n");

          if (!isBlock) {
            return <code className="io-inline-code">{props.children}</code>;
          }

          return <CodeBlock code={text} language={languageMatch?.[1] ?? inferCodeLanguage(text)} />;
        },
      }}
    >
      {markdown}
    </Markdown>
  );
}

function PrettyStringValue({
  label,
  value,
  depth,
  siblingData,
  onOpenDocument,
}: {
  label: string | null;
  value: string;
  depth: number;
  siblingData?: Record<string, unknown>;
  onOpenDocument: (doc: DetectedDocument) => void;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const [expanded, setExpanded] = useState(!shouldCollapseLongText(value));
  const detectedDoc = detectDocument(value, siblingData);
  const classification = classifyStringContent(value);
  const canToggleRaw =
    Boolean(detectedDoc) ||
    classification.kind === "json" ||
    classification.kind === "markdown" ||
    classification.kind === "xml";
  const canCollapseVisibleText = shouldCollapseLongText(value) && (showRaw || classification.kind === "plain");

  const actions = (
    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
      {canToggleRaw && (
        <RawToggleIconButton
          showingRaw={showRaw}
          onClick={() => setShowRaw((current) => !current)}
        />
      )}
      {canCollapseVisibleText && (
        <ChevronToggleButton
          expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
          title={expanded ? "Collapse" : "Expand"}
        />
      )}
    </div>
  );

  if (detectedDoc && !showRaw) {
    return (
      <PrettyCard label={label} badge={detectedDoc.type} depth={depth} actions={actions}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
          <span style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
            {formatFileSize(detectedDoc.size)} · {detectedDoc.mimeType}
          </span>
          <button
            onClick={() => onOpenDocument(detectedDoc)}
            style={{
              border: "1px solid var(--color-border)",
              borderRadius: "6px",
              background: "var(--color-surface-warm)",
              color: "var(--color-text)",
              padding: "4px 8px",
              fontSize: "12px",
              cursor: "pointer",
            }}
          >
            {`Open ${detectedDoc.type.toUpperCase()}`}
          </button>
        </div>
      </PrettyCard>
    );
  }

  if (classification.kind === "json" && !showRaw && depth < MAX_PRETTY_DEPTH) {
    return (
      <PrettyCard label={label} badge={classification.label} depth={depth} actions={actions}>
        <PrettyValue
          label={null}
          value={classification.parsed}
          depth={depth + 1}
          siblingData={isRecord(classification.parsed) ? classification.parsed : undefined}
          onOpenDocument={onOpenDocument}
        />
      </PrettyCard>
    );
  }

  if (classification.kind === "markdown" && !showRaw) {
    return (
      <PrettyCard label={label} badge="markdown" depth={depth} actions={actions}>
        <MarkdownContent markdown={value} />
      </PrettyCard>
    );
  }

  if (classification.kind === "xml" && !showRaw) {
    return (
      <PrettyCard label={label} badge="xml" depth={depth} actions={actions}>
        <CodeBlock code={value} language="xml" />
      </PrettyCard>
    );
  }

  if (classification.kind === "code" && !showRaw) {
    const code = classification.fenced ? (unwrapFencedCode(value)?.code ?? value) : value;
    return (
      <PrettyCard
        label={label}
        badge={classification.fenced ? `fenced · ${classification.language}` : `code · ${classification.language}`}
        depth={depth}
      >
        <CodeBlock code={code} language={classification.language} />
      </PrettyCard>
    );
  }

  return (
    <PrettyCard label={label} badge="string" depth={depth} actions={actions}>
      <pre
        style={{
          margin: 0,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace',
          fontSize: "12.5px",
          lineHeight: "1.55",
          color: "#43884e",
        }}
      >
        {expanded ? value : getStringPreview(value)}
      </pre>
    </PrettyCard>
  );
}

function PrettyArrayValue({
  label,
  value,
  depth,
  onOpenDocument,
}: {
  label: string | null;
  value: unknown[];
  depth: number;
  onOpenDocument: (doc: DetectedDocument) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const columns = getUniformObjectArrayColumns(value);

  let content: React.ReactNode;
  if (!expanded) {
    content = <div style={{ color: "var(--color-text-muted)", fontSize: "13px" }}>{`${value.length} items`}</div>;
  } else if (value.length === 0) {
    content = <div style={{ color: "var(--color-text-muted)", fontSize: "13px" }}>Empty array</div>;
  } else if (columns) {
    content = (
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {value.map((row, rowIndex) => (
              <tr key={`row-${rowIndex}`}>
                {columns.map((column) => {
                  const cell = (row as Record<string, unknown>)[column];
                  const rendered = typeof cell === "string" ? getStringPreview(cell, 90) : stringifyScalar(cell);
                  return <td key={`${rowIndex}-${column}`}>{rendered}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  } else {
    content = (
      <div style={{ display: "grid", gap: "10px" }}>
        {value.map((item, index) => (
          isInlineSimpleValue(item) ? (
            <InlineArrayItemRow key={`array-${index}`} index={index} value={item} />
          ) : (
            <ArrayItemBox key={`array-${index}`} index={index}>
              <PrettyValue
                label={null}
                value={item}
                depth={depth + 1}
                siblingData={isRecord(item) ? item : undefined}
                onOpenDocument={onOpenDocument}
              />
            </ArrayItemBox>
          )
        ))}
      </div>
    );
  }

  return (
    <PrettyCard
      label={label}
      badge={`list · ${value.length}`}
      depth={depth}
      actions={<ChevronToggleButton expanded={expanded} onClick={() => setExpanded((current) => !current)} title={expanded ? "Collapse" : "Expand"} />}
    >
      {content}
    </PrettyCard>
  );
}

function PrettyObjectValue({
  label,
  value,
  depth,
  onOpenDocument,
}: {
  label: string | null;
  value: Record<string, unknown>;
  depth: number;
  onOpenDocument: (doc: DetectedDocument) => void;
}) {
  const entries = Object.entries(value);
  const content = (
    <div style={{ display: "grid", gap: "10px" }}>
      {entries.map(([childKey, childValue]) => (
        isInlineSimpleValue(childValue, value) ? (
          <InlineValueRow key={childKey} label={childKey} value={childValue} />
        ) : (
          <PrettyValue
            key={childKey}
            label={childKey}
            value={childValue}
            depth={depth + 1}
            siblingData={value}
            onOpenDocument={onOpenDocument}
          />
        )
      ))}
    </div>
  );

  if (label === null) {
    return content;
  }

  return (
    <PrettyCard label={label} badge={`object · ${entries.length}`} depth={depth}>
      {entries.length > 0 ? content : <div style={{ color: "var(--color-text-muted)", fontSize: "13px" }}>Empty object</div>}
    </PrettyCard>
  );
}

function PrettyValue({
  label,
  value,
  depth,
  siblingData,
  onOpenDocument,
}: {
  label: string | null;
  value: unknown;
  depth: number;
  siblingData?: Record<string, unknown>;
  onOpenDocument: (doc: DetectedDocument) => void;
}) {
  if (depth > MAX_PRETTY_DEPTH) {
    return (
      <PrettyCard label={label} badge="nested" depth={depth} compact>
        <div
          style={{
            fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace',
            fontSize: "12px",
            color: "var(--color-text-muted)",
          }}
        >
          More nested content is hidden here. Switch to JSON view to inspect it.
        </div>
      </PrettyCard>
    );
  }

  if (value === null || typeof value === "number" || typeof value === "boolean") {
    return <ScalarBox label={label} value={value} depth={depth} />;
  }

  if (typeof value === "string") {
    return (
      <PrettyStringValue
        label={label}
        value={value}
        depth={depth}
        siblingData={siblingData}
        onOpenDocument={onOpenDocument}
      />
    );
  }

  if (Array.isArray(value)) {
    return <PrettyArrayValue label={label} value={value} depth={depth} onOpenDocument={onOpenDocument} />;
  }

  if (isRecord(value)) {
    return <PrettyObjectValue label={label} value={value} depth={depth} onOpenDocument={onOpenDocument} />;
  }

  return <ScalarBox label={label} value={String(value)} depth={depth} />;
}

function PrettyContent({
  data,
  onOpenDocument,
}: {
  data: Record<string, unknown>;
  onOpenDocument: (doc: DetectedDocument) => void;
}) {
  return (
    <div className="io-pretty-content">
      <PrettyValue label={null} value={data} depth={0} siblingData={data} onOpenDocument={onOpenDocument} />
    </div>
  );
}

function IOPanel({
  label,
  data,
  viewMode,
  nodeId,
  editLock,
  isEdited,
  hasAnyEdit,
  onStartEdit,
  onSaveEdit,
  onSaveAndRerun,
  onCancelEdit,
}: {
  label: string;
  data: Record<string, unknown>;
  viewMode: "pretty" | "json";
  nodeId?: string;
  editLock: EditKey | null;
  isEdited: boolean;
  hasAnyEdit: boolean;
  onStartEdit: (nodeId: string, label: "Input" | "Output") => void;
  onSaveEdit: (nodeId: string, label: "Input" | "Output", newData: string) => void;
  onSaveAndRerun: (nodeId: string, label: "Input" | "Output", newData: string) => void;
  onCancelEdit: () => void;
}) {
  const jsonStr = useMemo(() => JSON.stringify(data, null, 2), [data]);
  const attachments = useMemo(() => extractAttachments(data), [data]);
  const [editValue, setEditValue] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [ghost, setGhost] = useState("");
  const ghostTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const myKey: EditKey = `${nodeId}:${label as "Input" | "Output"}`;
  const isActiveEdit = editLock === myKey;
  const isLocked = (editLock !== null && !isActiveEdit) || (hasAnyEdit && !isEdited);
  const handleOpenDocument = useCallback((doc: DetectedDocument) => {
    const binary = atob(doc.data);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    const blob = new Blob([bytes], { type: doc.mimeType });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `document.${getFileExtension(doc.type)}`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, []);

  const generateGhost = useCallback((value: string) => {
    if (ghostTimer.current) clearTimeout(ghostTimer.current);
    setGhost("");
    if (!value.trim()) return;
    ghostTimer.current = setTimeout(() => {
      const lastLine = value.split("\n").pop()?.trimEnd() ?? "";
      let suggestion = "";
      if (lastLine.endsWith('"')) {
        suggestion = ": ";
      } else if (lastLine.endsWith(": ")) {
        suggestion = '"value"';
      } else if (lastLine.endsWith(",")) {
        suggestion = '\n    "key": "value"';
      } else if (lastLine.endsWith("{")) {
        suggestion = '\n    "key": "value"\n  }';
      } else if (/"\w+$/.test(lastLine)) {
        const partial = lastLine.match(/"(\w+)$/)?.[1] ?? "";
        const completions: Record<string, string> = {
          ro: 'le": "user"',
          con: 'tent": ""',
          mod: 'el": "gpt-4o"',
          tem: 'perature": 0',
          max: '_tokens": 1024',
          sys: 'tem"',
          mes: 'sages": []',
        };
        for (const [prefix, rest] of Object.entries(completions)) {
          if (partial.startsWith(prefix) && partial.length <= prefix.length + 2) {
            suggestion = rest;
            break;
          }
        }
      }
      if (suggestion) setGhost(suggestion);
    }, 400);
  }, []);

  const handleEditChange = useCallback((event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = event.target.value;
    setEditValue(value);
    generateGhost(value);
  }, [generateGhost]);

  const handleEditKeyDown = useCallback((event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Tab" && ghost) {
      event.preventDefault();
      const nextValue = editValue + ghost;
      setEditValue(nextValue);
      setGhost("");
      generateGhost(nextValue);
    }
    if (event.key === "Escape" && ghost) {
      setGhost("");
    }
  }, [editValue, generateGhost, ghost]);

  const startEdit = useCallback(() => {
    if (!nodeId || isLocked) return;
    setEditValue(JSON.stringify(data, null, 2));
    setGhost("");
    onStartEdit(nodeId, label as "Input" | "Output");
  }, [data, isLocked, label, nodeId, onStartEdit]);

  const cancelEdit = useCallback(() => {
    setEditValue("");
    onCancelEdit();
  }, [onCancelEdit]);

  const saveEdit = useCallback(() => {
    if (nodeId) {
      onSaveEdit(nodeId, label as "Input" | "Output", editValue);
    }
  }, [editValue, label, nodeId, onSaveEdit]);

  const saveAndRerun = useCallback(() => {
    if (nodeId) {
      onSaveAndRerun(nodeId, label as "Input" | "Output", editValue);
    }
  }, [editValue, label, nodeId, onSaveAndRerun]);

  const handleSuggest = useCallback(() => {
    setSuggesting(true);
    setTimeout(() => {
      try {
        const parsed = JSON.parse(editValue || jsonStr);
        setEditValue(JSON.stringify(parsed, null, 2));
      } catch {
        // Keep current value.
      }
      setSuggesting(false);
    }, 1200);
  }, [editValue, jsonStr]);

  return (
    <div className={`io-panel${isEdited ? " io-panel-edited" : ""}`} onClick={(event) => event.stopPropagation()}>
      <div className="io-panel-header">
        <span className="io-panel-label">
          {label}
          {isEdited && (
            <span className="io-edited-badge">
              <Pencil size={9} /> edited
            </span>
          )}
        </span>
        <div className="io-panel-actions">
          {!isActiveEdit && (
            <div className={isLocked ? "io-edit-locked-wrapper" : ""} title={isLocked ? "Finish the current edit before editing another field" : `Edit ${label.toLowerCase()}`}>
              <button className="io-edit-btn" onClick={startEdit} disabled={isLocked}>
                <Pencil size={11} /> Edit
              </button>
            </div>
          )}
          {isActiveEdit && (
            <button
              className="io-suggest-btn"
              onClick={handleSuggest}
              disabled={suggesting}
              title="Get AI suggestion"
            >
              {suggesting ? (
                <><Loader2 size={11} className="fa-spinner" /> Suggesting…</>
              ) : (
                <><Sparkles size={11} /> Suggest Edit</>
              )}
            </button>
          )}
        </div>
      </div>
      <div className="io-panel-content">
        {isActiveEdit ? (
          <div className="io-edit-area">
            <div className="io-edit-wrapper">
              <div className="io-edit-ghost" aria-hidden>
                <span style={{ color: "transparent" }}>{editValue}</span>
                {ghost && <span className="io-edit-ghost-suggestion">{ghost}</span>}
              </div>
              <textarea
                className="io-edit-textarea"
                value={editValue}
                onChange={handleEditChange}
                onKeyDown={handleEditKeyDown}
                spellCheck={false}
                style={{ background: "transparent", position: "relative", zIndex: 1 }}
              />
              {ghost && <span className="io-edit-ghost-hint">Tab to accept</span>}
            </div>
            <div className="io-edit-toolbar">
              <button className="io-edit-save-rerun" onClick={saveAndRerun}>Save and Rerun</button>
              <button className="io-edit-save" onClick={saveEdit}>Save</button>
              <button className="io-edit-cancel" onClick={cancelEdit}>Cancel</button>
            </div>
          </div>
        ) : viewMode === "json" ? (
          <CodeBlock code={jsonStr} language="json" />
        ) : (
          <PrettyContent data={data} onOpenDocument={handleOpenDocument} />
        )}
        {attachments.length > 0 && (
          <>
            <div className="io-attachments-header">Files in this message</div>
            <AttachmentStrip attachments={attachments} />
          </>
        )}
      </div>
    </div>
  );
}

function NodeHeader({ node }: { node: GraphNode }) {
  const shortId = node.id.length > 8 ? node.id.slice(0, 8) : node.id;
  const [copied, setCopied] = useState(false);

  const handleCopyId = useCallback(() => {
    navigator.clipboard.writeText(node.id);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [node.id]);

  return (
    <div className="node-card-header">
      <div className="node-card-title-row">
        <span className="node-card-name">{node.label}</span>
      </div>
      <div className="node-card-meta-row">
        {node.model && <span className="node-card-type llm">{node.model}</span>}
        <span className="node-card-id" title={node.id}>
          {shortId}
          <button className="node-card-id-copy" onClick={handleCopyId} title="Copy full node ID">
            <Copy size={10} />
          </button>
          {copied && <span className="node-card-id-copied">Copied!</span>}
        </span>
      </div>
    </div>
  );
}

export function RunTraceFlow({
  nodes,
  edges,
  viewMode,
  focusedNodeId,
  nodeRefs,
  onCardClick,
  editLock,
  editedFields,
  onStartEdit,
  onSaveEdit,
  onSaveAndRerun,
  onCancelEdit,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  viewMode: "pretty" | "json";
  focusedNodeId: string | null;
  nodeRefs: React.MutableRefObject<Map<string, HTMLDivElement>>;
  onCardClick: (nodeId: string) => void;
  editLock: EditKey | null;
  editedFields: Set<EditKey>;
  onStartEdit: (nodeId: string, label: "Input" | "Output") => void;
  onSaveEdit: (nodeId: string, label: "Input" | "Output", newData: string) => void;
  onSaveAndRerun: (nodeId: string, label: "Input" | "Output", newData: string) => void;
  onCancelEdit: () => void;
}) {
  const sortedNodes = useMemo(() => topoSortNodes(nodes, edges), [nodes, edges]);
  const hasAnyEdit = editedFields.size > 0;

  return (
    <div className="run-detail-io-scroll">
      {sortedNodes.map((node) => {
        const hasEdit = editedFields.has(`${node.id}:Input`) || editedFields.has(`${node.id}:Output`);
        return (
          <div
            key={node.id}
            ref={(element) => {
              if (element) nodeRefs.current.set(node.id, element);
            }}
            className={`trace-node-card${node.id === focusedNodeId ? " focused" : ""}${hasEdit ? " trace-node-edited" : ""}`}
            onClick={() => {
              if (node.id !== focusedNodeId) {
                onCardClick(node.id);
              }
            }}
          >
            <NodeHeader node={node} />
            <IOPanel
              label="Input"
              data={node.input}
              viewMode={viewMode}
              nodeId={node.id}
              editLock={editLock}
              isEdited={editedFields.has(`${node.id}:Input`)}
              hasAnyEdit={hasAnyEdit}
              onStartEdit={onStartEdit}
              onSaveEdit={onSaveEdit}
              onSaveAndRerun={onSaveAndRerun}
              onCancelEdit={onCancelEdit}
            />
            <IOPanel
              label="Output"
              data={node.output}
              viewMode={viewMode}
              nodeId={node.id}
              editLock={editLock}
              isEdited={editedFields.has(`${node.id}:Output`)}
              hasAnyEdit={hasAnyEdit}
              onStartEdit={onStartEdit}
              onSaveEdit={onSaveEdit}
              onSaveAndRerun={onSaveAndRerun}
              onCancelEdit={onCancelEdit}
            />
          </div>
        );
      })}
    </div>
  );
}
