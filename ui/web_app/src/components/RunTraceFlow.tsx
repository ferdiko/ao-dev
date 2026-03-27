import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AttachmentStrip } from "./AttachmentPreview";
import { extractAttachments, type Attachment } from "../attachmentUtils";
import { DocumentPreviewModal } from "./DocumentPreviewModal";
import { Pencil, Copy, ChevronDown, ChevronRight, Upload } from "lucide-react";
import {
  detectDocument,
  formatFileSize,
  isPreviewableDocument,
  type DetectedDocument,
} from "@sovara/shared-components/utils/documentDetection";
import { getExternalUrl } from "@sovara/shared-components/utils/urlUtils";
import { saveDocument } from "@sovara/shared-components/utils/documentDownload";
import { applyDocumentReplacement, pickReplacementDocumentFromBrowser } from "@sovara/shared-components/utils/documentReplacement";
import {
  detectFlattenedMessageGroups,
  detectMessageLikeArray,
  detectMessageLikeObject,
  type FlattenedMessageGroup,
  type MessageMetadataEntry,
  type MessageRoleStyle,
} from "@sovara/shared-components/utils/messageLike";
import { type PrismStyleMap, withTransparentPrismTheme } from "@sovara/shared-components/utils/prismTheme";
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
  /(^|[\s(])\*\*[^*\n][^*\n]*\*\*(?=$|[\s).,:;!?])/m,
  /(^|[\s(])__[^_\n][^_\n]*__(?=$|[\s).,:;!?])/m,
  /~~[^~\n][^~\n]*~~/m,
];

type StringClassification =
  | { kind: "json"; parsed: unknown; label: "json object" | "json list" }
  | { kind: "markdown" }
  | { kind: "code"; language: string; fenced: boolean }
  | { kind: "xml" }
  | { kind: "plain" };

type JsonPath = string[];
type JumpTarget = { path: JsonPath; cursorOffset: number | null; selectedText: string | null };
type MarkdownCodeProps = {
  children?: React.ReactNode;
  className?: string;
};

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
  if (inlineCodeMatches.length >= 2 && value.includes("\n")) {
    return true;
  }

  if (inlineCodeMatches.length >= 1 && value.includes("\n")) {
    return true;
  }

  return false;
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

  if (/^\s*#!\/bin\/(ba)?sh/m.test(trimmed) || /(^|\n)\s*(echo|export|cd|grep|uv|python3?)\b/.test(trimmed)) {
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

function getSelectionLeafOffset(): number | null {
  if (typeof window === "undefined") {
    return null;
  }

  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) {
    return null;
  }

  return Math.max(0, selection.getRangeAt(0).startOffset);
}

function getSelectionLeafText(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  const selection = window.getSelection();
  if (!selection) {
    return null;
  }

  const text = selection.toString().trim();
  if (!text) {
    return null;
  }

  return text.length <= 120 ? text : text.slice(0, 120);
}

function getSerializedValueOffset(value: unknown, cursorOffset: number | null): number {
  if (cursorOffset === null) {
    return 0;
  }

  const safeOffset = Math.max(0, cursorOffset);
  if (typeof value === "string") {
    const prefix = value.slice(0, safeOffset);
    return Math.max(0, JSON.stringify(prefix).length - 1);
  }

  const scalarText = stringifyScalar(value);
  return Math.min(safeOffset, scalarText.length);
}

function getTransientSelectionRange(text: string, cursorOffset: number | null, selectedText: string | null): { start: number; end: number; caret: number } {
  const caret = Math.max(0, Math.min(cursorOffset ?? 0, text.length));
  if (text.length === 0) {
    return { start: caret, end: caret, caret };
  }

  const needle = selectedText?.trim();
  if (!needle) {
    return { start: caret, end: caret, caret };
  }

  let bestStart = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  let searchIndex = 0;
  while (searchIndex <= text.length) {
    const matchIndex = text.indexOf(needle, searchIndex);
    if (matchIndex === -1) {
      break;
    }

    const distance = Math.abs(matchIndex - caret);
    if (distance < bestDistance) {
      bestStart = matchIndex;
      bestDistance = distance;
    }
    searchIndex = matchIndex + 1;
  }

  if (bestStart === -1) {
    return { start: caret, end: caret, caret };
  }

  return { start: bestStart, end: bestStart + needle.length, caret: bestStart };
}

function scrollTextareaOffsetIntoView(textarea: HTMLTextAreaElement, offset: number): void {
  if (typeof document === "undefined") {
    return;
  }

  const clampedOffset = Math.max(0, Math.min(offset, textarea.value.length));
  const styles = window.getComputedStyle(textarea);
  const mirror = document.createElement("div");
  const marker = document.createElement("span");

  mirror.style.position = "absolute";
  mirror.style.visibility = "hidden";
  mirror.style.pointerEvents = "none";
  mirror.style.zIndex = "-1";
  mirror.style.whiteSpace = "pre-wrap";
  mirror.style.overflowWrap = "break-word";
  mirror.style.wordBreak = "break-word";
  mirror.style.boxSizing = "border-box";
  mirror.style.width = `${textarea.clientWidth}px`;
  mirror.style.padding = styles.padding;
  mirror.style.border = styles.border;
  mirror.style.font = styles.font;
  mirror.style.fontFamily = styles.fontFamily;
  mirror.style.fontSize = styles.fontSize;
  mirror.style.fontWeight = styles.fontWeight;
  mirror.style.fontStyle = styles.fontStyle;
  mirror.style.letterSpacing = styles.letterSpacing;
  mirror.style.lineHeight = styles.lineHeight;
  mirror.style.textTransform = styles.textTransform;
  mirror.style.textIndent = styles.textIndent;
  mirror.style.tabSize = styles.tabSize;

  mirror.textContent = textarea.value.slice(0, clampedOffset);
  marker.textContent = textarea.value.slice(clampedOffset, clampedOffset + 1) || "\u200b";
  mirror.appendChild(marker);
  document.body.appendChild(mirror);

  const markerTop = marker.offsetTop;
  const lineHeight = Number.parseFloat(styles.lineHeight) || Number.parseFloat(styles.fontSize) * 1.6 || 20;
  textarea.scrollTop = Math.max(0, markerTop - textarea.clientHeight / 3 + lineHeight);

  mirror.remove();
}

function normalizeJsonText(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value));
  } catch {
    return value;
  }
}

function pathsEqual(left: JsonPath | null, right: JsonPath | null): boolean {
  if (!left || !right || left.length !== right.length) {
    return false;
  }

  return left.every((segment, index) => segment === right[index]);
}

function stringifyJsonWithOffset(value: unknown, targetPath: JsonPath | null, targetCursorOffset: number | null = null): { text: string; offset: number | null } {
  const indentUnit = "  ";

  const matchesTarget = (path: JsonPath) => pathsEqual(path, targetPath);

  const serialize = (currentValue: unknown, currentPath: JsonPath, indentLevel: number): { text: string; offset: number | null } => {
    if (Array.isArray(currentValue)) {
      if (currentValue.length === 0) {
        return { text: "[]", offset: matchesTarget(currentPath) ? 0 : null };
      }

      let text = "[";
      let offset = matchesTarget(currentPath) ? 0 : null;

      currentValue.forEach((item, index) => {
        const itemPath = [...currentPath, String(index)];
        text += `\n${indentUnit.repeat(indentLevel + 1)}`;
        const itemStart = text.length;
        if (matchesTarget(itemPath)) {
          offset = itemStart;
        }

        const child = serialize(item, itemPath, indentLevel + 1);
        if (child.offset !== null) {
          offset = itemStart + child.offset;
        }
        text += child.text;

        if (index < currentValue.length - 1) {
          text += ",";
        }
      });

      text += `\n${indentUnit.repeat(indentLevel)}]`;
      return { text, offset };
    }

    if (isRecord(currentValue)) {
      const entries = Object.entries(currentValue);
      if (entries.length === 0) {
        return { text: "{}", offset: matchesTarget(currentPath) ? 0 : null };
      }

      let text = "{";
      let offset = matchesTarget(currentPath) ? 0 : null;

      entries.forEach(([key, childValue], index) => {
        const childPath = [...currentPath, key];
        text += `\n${indentUnit.repeat(indentLevel + 1)}`;
        const entryStart = text.length;
        if (matchesTarget(childPath)) {
          offset = entryStart;
        }

        const keyPrefix = `${JSON.stringify(key)}: `;
        text += keyPrefix;
        const childStart = text.length;
        const child = serialize(childValue, childPath, indentLevel + 1);
        if (child.offset !== null) {
          offset = childStart + child.offset;
        }
        text += child.text;

        if (index < entries.length - 1) {
          text += ",";
        }
      });

      text += `\n${indentUnit.repeat(indentLevel)}}`;
      return { text, offset };
    }

    return {
      text: JSON.stringify(currentValue),
      offset: matchesTarget(currentPath) ? getSerializedValueOffset(currentValue, targetCursorOffset) : null,
    };
  };

  return serialize(value, [], 0);
}

function CodeBlock({
  code,
  language,
  onEdit,
  editDisabled = false,
  editTitle = "Edit this field",
  headerActions,
  embedded = false,
}: {
  code: string;
  language: string;
  onEdit?: () => void;
  editDisabled?: boolean;
  editTitle?: string;
  headerActions?: React.ReactNode;
  embedded?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [code]);

  return (
    <div
      className={!embedded ? "code-block" : undefined}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onDoubleClick={onEdit && !editDisabled ? (event) => {
        event.stopPropagation();
        onEdit();
      } : undefined}
      style={embedded ? { display: "grid", gap: "8px" } : undefined}
    >
      <div
        className={!embedded ? "code-block-header" : undefined}
        style={embedded ? { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px" } : undefined}
      >
        <span
          className={!embedded ? "code-block-lang" : undefined}
          style={embedded ? { fontSize: "11px", fontWeight: 600, color: "var(--color-text-muted)", letterSpacing: "0.02em" } : undefined}
        >
          {LANG_DISPLAY[language] ?? language}
        </span>
        <div
          className={!embedded ? "code-block-actions" : undefined}
          style={embedded ? { display: "inline-flex", alignItems: "center", gap: "8px" } : undefined}
        >
          {headerActions}
          {onEdit ? (
            <HoverAction visible={isHovered}>
              <EditIconButton onClick={onEdit} disabled={editDisabled} title={editTitle} />
            </HoverAction>
          ) : null}
          <button
            className="code-block-copy"
            onClick={(event) => {
              event.stopPropagation();
              handleCopy();
            }}
            onDoubleClick={(event) => {
              event.stopPropagation();
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
          padding: embedded ? "0" : "12px 14px",
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
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      onDoubleClick={(event) => {
        event.stopPropagation();
      }}
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

function HoverAction({
  visible,
  children,
}: {
  visible: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        opacity: visible ? 1 : 0,
        pointerEvents: visible ? "auto" : "none",
        transition: "opacity 120ms ease",
      }}
    >
      {children}
    </div>
  );
}

function EditIconButton({
  onClick,
  disabled = false,
  title,
}: {
  onClick: () => void;
  disabled?: boolean;
  title: string;
}) {
  return (
    <button
      onClick={(event) => {
        event.stopPropagation();
        if (!disabled) {
          onClick();
        }
      }}
      onDoubleClick={(event) => {
        event.stopPropagation();
      }}
      disabled={disabled}
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
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.45 : 1,
        padding: 0,
      }}
    >
      <Pencil size={12} />
    </button>
  );
}

function InlineHeaderIconButton({
  onClick,
  title,
  active = false,
  children,
}: {
  onClick: () => void;
  title: string;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      onDoubleClick={(event) => {
        event.stopPropagation();
      }}
      title={title}
      aria-label={title}
      className="code-block-copy"
      style={{
        borderRadius: "999px",
        border: active ? "1px solid rgba(67, 136, 78, 0.22)" : "1px solid transparent",
        background: active ? "rgba(67, 136, 78, 0.08)" : "none",
        minWidth: "20px",
        height: "20px",
        padding: "0 6px",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        lineHeight: 1,
      }}
    >
      {children}
    </button>
  );
}

function PrettyCard({
  label,
  badge,
  headerAddon,
  actions,
  onEdit,
  editDisabled = false,
  editTitle = "Edit this field",
  depth,
  compact = false,
  children,
}: {
  label: string | null;
  badge?: string;
  headerAddon?: React.ReactNode;
  actions?: React.ReactNode;
  onEdit?: () => void;
  editDisabled?: boolean;
  editTitle?: string;
  depth: number;
  compact?: boolean;
  children: React.ReactNode;
}) {
  const hasLeadingHeader = Boolean(label || badge || headerAddon);
  const [isHovered, setIsHovered] = useState(false);
  const editAction = onEdit ? (
    <HoverAction visible={isHovered}>
      <EditIconButton onClick={onEdit} disabled={editDisabled} title={editTitle} />
    </HoverAction>
  ) : null;
  const actionGroup = editAction && actions ? (
    <div style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
      {editAction}
      {actions}
    </div>
  ) : editAction || actions;

  return (
    <div
      style={{ marginBottom: "10px", marginLeft: depth > 0 ? "12px" : 0, position: "relative" }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onDoubleClick={onEdit && !editDisabled ? (event) => {
        event.stopPropagation();
        onEdit();
      } : undefined}
    >
      {hasLeadingHeader && (
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
            {headerAddon}
          </div>
          {actionGroup}
        </div>
      )}
      {!hasLeadingHeader && actionGroup && (
        <div
          style={{
            position: "absolute",
            top: compact ? "6px" : "8px",
            right: "8px",
            zIndex: 1,
          }}
        >
          {actionGroup}
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

function FramedContentBlock({
  label,
  onEdit,
  editDisabled = false,
  editTitle = "Edit this field",
  headerActions,
  children,
  embedded = false,
}: {
  label: string;
  onEdit?: () => void;
  editDisabled?: boolean;
  editTitle?: string;
  headerActions?: React.ReactNode;
  children: React.ReactNode;
  embedded?: boolean;
}) {
  const [isHovered, setIsHovered] = useState(false);
  const editAction = onEdit ? (
    <HoverAction visible={isHovered}>
      <EditIconButton onClick={onEdit} disabled={editDisabled} title={editTitle} />
    </HoverAction>
  ) : null;

  return (
    <div
      className={!embedded ? "code-block" : undefined}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onDoubleClick={onEdit && !editDisabled ? (event) => {
        event.stopPropagation();
        onEdit();
      } : undefined}
      style={embedded ? { display: "grid", gap: "8px" } : undefined}
    >
      <div
        className={!embedded ? "code-block-header" : undefined}
        style={embedded ? { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px" } : undefined}
      >
        <span
          className={!embedded ? "code-block-lang" : undefined}
          style={embedded ? { fontSize: "11px", fontWeight: 600, color: "var(--color-text-muted)", letterSpacing: "0.02em" } : undefined}
        >
          {label}
        </span>
        <div
          className={!embedded ? "code-block-actions" : undefined}
          style={embedded ? { display: "inline-flex", alignItems: "center", gap: "8px" } : undefined}
        >
          {headerActions}
          {editAction}
        </div>
      </div>
      <div style={{ padding: embedded ? 0 : "12px 14px" }}>{children}</div>
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

function UrlValue({ value, href }: { value: string; href?: string }) {
  const resolvedHref = href ?? getExternalUrl(value);
  if (!resolvedHref) {
    return null;
  }

  return (
    <a
      href={resolvedHref}
      target="_blank"
      rel="noreferrer"
      onClick={(event) => {
        event.stopPropagation();
      }}
      onDoubleClick={(event) => {
        event.stopPropagation();
      }}
      style={{
        display: "block",
        fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace',
        fontSize: "12.5px",
        lineHeight: "1.5",
        color: "#43884e",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        textDecoration: "underline",
        textDecorationColor: "rgba(138, 138, 126, 0.28)",
        textUnderlineOffset: "0.14em",
      }}
    >
      {value}
    </a>
  );
}

function MessageRolePill({ roleStyle }: { roleStyle: MessageRoleStyle }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "1px 7px",
        borderRadius: "999px",
        border: `1px solid ${roleStyle.light.border}`,
        background: roleStyle.light.background,
        color: roleStyle.light.text,
        fontSize: "10px",
        lineHeight: "14px",
        fontWeight: 600,
        letterSpacing: "0.01em",
        textTransform: "lowercase",
      }}
    >
      {roleStyle.label}
    </span>
  );
}

function formatMessageMetadataValue(value: unknown): string | null {
  if (value === null) return "null";
  if (typeof value === "string") return shouldCollapseLongText(value) ? getStringPreview(value, 72) : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

function MessageMetadataStrip({ metadata }: { metadata: MessageMetadataEntry[] }) {
  const visibleMetadata = metadata
    .map((entry) => ({ ...entry, text: formatMessageMetadataValue(entry.value) }))
    .filter((entry): entry is MessageMetadataEntry & { text: string } => Boolean(entry.text));

  if (visibleMetadata.length === 0) {
    return null;
  }

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "10px" }}>
      {visibleMetadata.map((entry) => (
        <span
          key={entry.path.join(".")}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "4px",
            padding: "2px 7px",
            borderRadius: "999px",
            border: "1px solid rgba(138, 138, 126, 0.12)",
            background: "rgba(138, 138, 126, 0.05)",
            color: "var(--color-text-muted)",
            fontSize: "11px",
            lineHeight: "16px",
          }}
        >
          <span style={{ fontWeight: 600 }}>{entry.key}</span>
          <span>{entry.text}</span>
        </span>
      ))}
    </div>
  );
}

function ScalarBox({
  label,
  value,
  depth,
  onEdit,
  editDisabled,
  editTitle,
}: {
  label: string | null;
  value: unknown;
  depth: number;
  onEdit?: () => void;
  editDisabled?: boolean;
  editTitle?: string;
}) {
  return (
    <PrettyCard
      label={label}
      badge={getScalarTypeLabel(value)}
      depth={depth}
      compact
      onEdit={onEdit}
      editDisabled={editDisabled}
      editTitle={editTitle}
    >
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
  onEdit,
  editDisabled = false,
  editTitle = "Edit this field",
}: {
  label: string;
  value: unknown;
  onEdit?: () => void;
  editDisabled?: boolean;
  editTitle?: string;
}) {
  const isString = typeof value === "string";
  const externalUrl = isString ? getExternalUrl(value) : null;
  const [isHovered, setIsHovered] = useState(false);
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
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onDoubleClick={onEdit && !editDisabled ? (event) => {
        event.stopPropagation();
        onEdit();
      } : undefined}
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
          externalUrl ? (
            <UrlValue value={value} />
          ) : (
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
          )
        ) : (
          <CompactScalarValue value={value} />
        )}
      </div>
      {onEdit && (
        <HoverAction visible={isHovered}>
          <EditIconButton onClick={onEdit} disabled={editDisabled} title={editTitle} />
        </HoverAction>
      )}
    </div>
  );
}

function ArrayItemBox({
  headerAddon,
  children,
  onEdit,
  editDisabled = false,
  editTitle = "Edit this field",
}: {
  headerAddon?: React.ReactNode;
  children: React.ReactNode;
  onEdit?: () => void;
  editDisabled?: boolean;
  editTitle?: string;
}) {
  const [isHovered, setIsHovered] = useState(false);
  return (
    <div
      style={{
        border: "1px solid rgba(138, 138, 126, 0.14)",
        borderRadius: "8px",
        background: "rgba(255,255,255,0.26)",
        padding: "8px 10px",
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onDoubleClick={onEdit && !editDisabled ? (event) => {
        event.stopPropagation();
        onEdit();
      } : undefined}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", marginBottom: "6px" }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: "8px", minWidth: 0 }}>{headerAddon}</div>
        {onEdit && (
          <HoverAction visible={isHovered}>
            <EditIconButton onClick={onEdit} disabled={editDisabled} title={editTitle} />
          </HoverAction>
        )}
      </div>
      {children}
    </div>
  );
}

function InlineArrayItemRow({
  value,
  onEdit,
  editDisabled = false,
  editTitle = "Edit this field",
}: {
  value: unknown;
  onEdit?: () => void;
  editDisabled?: boolean;
  editTitle?: string;
}) {
  const isString = typeof value === "string";
  const externalUrl = isString ? getExternalUrl(value) : null;
  const [isHovered, setIsHovered] = useState(false);

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
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onDoubleClick={onEdit && !editDisabled ? (event) => {
        event.stopPropagation();
        onEdit();
      } : undefined}
    >
      <div style={{ minWidth: 0, flex: 1 }}>
        {isString ? (
          externalUrl ? (
            <UrlValue value={value} />
          ) : (
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
          )
        ) : (
          <CompactScalarValue value={value} />
        )}
      </div>
      {onEdit && (
        <HoverAction visible={isHovered}>
          <EditIconButton onClick={onEdit} disabled={editDisabled} title={editTitle} />
        </HoverAction>
      )}
    </div>
  );
}

function MarkdownContent({ markdown }: { markdown: string }) {
  return (
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

          return <CodeBlock code={text} language={languageMatch?.[1] ?? inferCodeLanguage(text)} />;
        },
      }}
    >
      {markdown}
    </Markdown>
  );
}

function MessageBubbleBody({
  value,
  depth,
  path,
  onJumpToEdit,
  onReplaceDocument,
  editDisabled,
  editTitle,
  onOpenDocument,
  expandPlainText = true,
  suppressArrayHeader = false,
  suppressNestedShell = false,
}: {
  value: unknown;
  depth: number;
  path: JsonPath;
  onJumpToEdit?: (path: JsonPath) => void;
  onReplaceDocument?: (path: JsonPath, doc: DetectedDocument) => void;
  editDisabled?: boolean;
  editTitle?: string;
  onOpenDocument: (doc: DetectedDocument) => void;
  expandPlainText?: boolean;
  suppressArrayHeader?: boolean;
  suppressNestedShell?: boolean;
}) {
  if (typeof value === "string") {
    return (
      <PrettyStringValue
        label={null}
        value={value}
        depth={depth}
        path={path}
        onJumpToEdit={onJumpToEdit}
        onReplaceDocument={onReplaceDocument}
        editDisabled={editDisabled}
        editTitle={editTitle}
        onOpenDocument={onOpenDocument}
        expandPlainText={expandPlainText}
        suppressNestedShell={suppressNestedShell}
      />
    );
  }

  return (
    <PrettyValue
      label={null}
      value={value}
      depth={depth}
      path={path}
      siblingData={isRecord(value) ? value : undefined}
      onJumpToEdit={onJumpToEdit}
      onReplaceDocument={onReplaceDocument}
      editDisabled={editDisabled}
      editTitle={editTitle}
      onOpenDocument={onOpenDocument}
      suppressArrayHeader={suppressArrayHeader}
      suppressNestedShell={suppressNestedShell}
    />
  );
}

function FlattenedMessageGroupCard({
  group,
  depth,
  onJumpToEdit,
  onReplaceDocument,
  editDisabled,
  editTitle,
  onOpenDocument,
}: {
  group: FlattenedMessageGroup;
  depth: number;
  onJumpToEdit?: (path: JsonPath) => void;
  onReplaceDocument?: (path: JsonPath, doc: DetectedDocument) => void;
  editDisabled?: boolean;
  editTitle?: string;
  onOpenDocument: (doc: DetectedDocument) => void;
}) {
  if (group.detectedMessages) {
    const detectedMessages = group.detectedMessages;
    const contentBadge = detectedMessages.length === 1 && Array.isArray(detectedMessages[0].content)
      ? `list · ${detectedMessages[0].content.length}`
      : `list · ${detectedMessages.length}`;
    return (
      <PrettyCard
        label={group.messageKey}
        badge={contentBadge}
        headerAddon={detectedMessages.length === 1 ? <MessageRolePill roleStyle={detectedMessages[0].roleStyle} /> : undefined}
        depth={depth}
      >
        {detectedMessages.length === 1 ? (
          <div style={{ display: "grid", gap: "8px" }}>
            <MessageBubbleBody
              value={detectedMessages[0].content}
              depth={depth + 1}
              path={[group.messageKey, "0", ...detectedMessages[0].contentPath]}
              onJumpToEdit={onJumpToEdit}
              onReplaceDocument={onReplaceDocument}
              editDisabled={editDisabled}
              editTitle={editTitle}
              onOpenDocument={onOpenDocument}
              suppressArrayHeader
              suppressNestedShell
            />
            <MessageMetadataStrip metadata={[...group.metadata, ...detectedMessages[0].metadata]} />
          </div>
        ) : (
          <div style={{ display: "grid", gap: "10px" }}>
            {detectedMessages.map((message, index) => (
              <ArrayItemBox
                key={`group-message-${index}`}
                headerAddon={<MessageRolePill roleStyle={message.roleStyle} />}
              >
                <div style={{ display: "grid", gap: "8px" }}>
                  <MessageBubbleBody
                    value={message.content}
                    depth={depth + 1}
                    path={[group.messageKey, String(index), ...message.contentPath]}
                    onJumpToEdit={onJumpToEdit}
                  onReplaceDocument={onReplaceDocument}
                  editDisabled={editDisabled}
                  editTitle={editTitle}
                  onOpenDocument={onOpenDocument}
                  suppressArrayHeader
                  suppressNestedShell
                />
                  <MessageMetadataStrip metadata={message.metadata} />
                </div>
              </ArrayItemBox>
            ))}
            <MessageMetadataStrip metadata={group.metadata} />
          </div>
        )}
      </PrettyCard>
    );
  }

  if (group.detectedMessage) {
    const contentBadge = Array.isArray(group.detectedMessage.content) ? `list · ${group.detectedMessage.content.length}` : undefined;
    return (
      <PrettyCard
        label={group.messageKey}
        badge={contentBadge}
        headerAddon={<MessageRolePill roleStyle={group.detectedMessage.roleStyle} />}
        depth={depth}
      >
        <MessageBubbleBody
          value={group.detectedMessage.content}
          depth={depth + 1}
          path={[group.messageKey, ...group.detectedMessage.contentPath]}
          onJumpToEdit={onJumpToEdit}
          onReplaceDocument={onReplaceDocument}
          editDisabled={editDisabled}
          editTitle={editTitle}
          onOpenDocument={onOpenDocument}
          suppressArrayHeader
          suppressNestedShell
        />
        <MessageMetadataStrip metadata={[...group.metadata, ...group.detectedMessage.metadata]} />
      </PrettyCard>
    );
  }

  return null;
}

function PrettyStringValue({
  label,
  value,
  depth,
  path,
  siblingData,
  onJumpToEdit,
  onReplaceDocument,
  editDisabled,
  editTitle,
  onOpenDocument,
  expandPlainText = false,
  suppressNestedShell = false,
}: {
  label: string | null;
  value: string;
  depth: number;
  path: JsonPath;
  siblingData?: Record<string, unknown>;
  onJumpToEdit?: (path: JsonPath) => void;
  onReplaceDocument?: (path: JsonPath, doc: DetectedDocument) => void;
  editDisabled?: boolean;
  editTitle?: string;
  onOpenDocument: (doc: DetectedDocument) => void;
  expandPlainText?: boolean;
  suppressNestedShell?: boolean;
}) {
  const shouldCollapse = shouldCollapseLongText(value);
  const [expanded, setExpanded] = useState(expandPlainText || !shouldCollapse);
  const [showMarkdownRaw, setShowMarkdownRaw] = useState(false);
  const detectedDoc = detectDocument(value, siblingData);
  const externalUrl = getExternalUrl(value);
  const classification = classifyStringContent(value);
  const canCollapseVisibleText = !expandPlainText && shouldCollapse && classification.kind === "plain";
  const renderEmbedded = suppressNestedShell && label === null;
  const actions = canCollapseVisibleText ? (
    <ChevronToggleButton
      expanded={expanded}
      onClick={() => setExpanded((current) => !current)}
      title={expanded ? "Collapse" : "Expand"}
    />
  ) : undefined;

  if (detectedDoc) {
    return (
      <PrettyCard
        label={label}
        badge={detectedDoc.type}
        depth={depth}
        actions={actions}
        onEdit={onJumpToEdit ? () => onJumpToEdit(path) : undefined}
        editDisabled={editDisabled}
        editTitle={editTitle}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
          <span style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
            {formatFileSize(detectedDoc.size)} · {detectedDoc.mimeType}
          </span>
          <button
            onClick={(event) => {
              event.stopPropagation();
              onOpenDocument(detectedDoc);
            }}
            onDoubleClick={(event) => {
              event.stopPropagation();
            }}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              border: "1px solid var(--color-border)",
              borderRadius: "6px",
              background: "var(--color-surface-warm)",
              color: "var(--color-text)",
              height: "28px",
              boxSizing: "border-box",
              padding: "0 8px",
              fontSize: "12px",
              lineHeight: 1,
              cursor: "pointer",
            }}
          >
            {`Open ${detectedDoc.type.toUpperCase()}`}
          </button>
          {onReplaceDocument && detectedDoc.type !== "unknown" && (
            <button
              onClick={(event) => {
                event.stopPropagation();
                onReplaceDocument(path, detectedDoc);
              }}
              onDoubleClick={(event) => {
                event.stopPropagation();
              }}
              title="Replace file"
              aria-label="Replace file"
              style={{
                boxSizing: "border-box",
                border: "1px solid var(--color-border)",
                borderRadius: "6px",
                background: "var(--color-surface-warm)",
                color: "var(--color-text)",
                width: "28px",
                height: "28px",
                padding: 0,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                lineHeight: 1,
                cursor: "pointer",
              }}
            >
              <Upload size={13} />
            </button>
          )}
        </div>
      </PrettyCard>
    );
  }

  if (classification.kind === "json" && depth < MAX_PRETTY_DEPTH) {
    return (
      <PrettyCard
        label={label}
        badge={classification.label}
        depth={depth}
        actions={actions}
        onEdit={onJumpToEdit ? () => onJumpToEdit(path) : undefined}
        editDisabled={editDisabled}
        editTitle={editTitle}
      >
        <PrettyValue
          label={null}
          value={classification.parsed}
          depth={depth + 1}
          path={path}
          siblingData={isRecord(classification.parsed) ? classification.parsed : undefined}
          onJumpToEdit={undefined}
          editDisabled={editDisabled}
          editTitle={editTitle}
          onOpenDocument={onOpenDocument}
        />
      </PrettyCard>
    );
  }

  if (classification.kind === "markdown") {
    const content = (
      <FramedContentBlock
        label="MARKDOWN"
        onEdit={onJumpToEdit ? () => onJumpToEdit(path) : undefined}
        editDisabled={editDisabled}
        editTitle={editTitle}
        embedded={renderEmbedded}
        headerActions={
          <InlineHeaderIconButton
            title={showMarkdownRaw ? "Show rendered markdown" : "Show raw markdown"}
            onClick={() => setShowMarkdownRaw((current) => !current)}
            active={showMarkdownRaw}
          >
            <span style={{ fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace', fontSize: "11px" }}>{"{}"}</span>
          </InlineHeaderIconButton>
        }
      >
        {showMarkdownRaw ? (
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
            {value}
          </pre>
        ) : (
          <MarkdownContent markdown={value} />
        )}
      </FramedContentBlock>
    );

    if (renderEmbedded) {
      return content;
    }

    return (
      <PrettyCard label={label} depth={depth} actions={actions}>
        {content}
      </PrettyCard>
    );
  }

  if (classification.kind === "xml") {
    const content = (
      <CodeBlock
        code={value}
        language="xml"
        onEdit={onJumpToEdit ? () => onJumpToEdit(path) : undefined}
        editDisabled={editDisabled}
        editTitle={editTitle}
        embedded={renderEmbedded}
      />
    );

    if (renderEmbedded) {
      return content;
    }

    return (
      <PrettyCard label={label} depth={depth} actions={actions}>
        {content}
      </PrettyCard>
    );
  }

  if (classification.kind === "code") {
    const code = classification.fenced ? (unwrapFencedCode(value)?.code ?? value) : value;
    const content = (
      <CodeBlock
        code={code}
        language={classification.language}
        onEdit={onJumpToEdit ? () => onJumpToEdit(path) : undefined}
        editDisabled={editDisabled}
        editTitle={editTitle}
        embedded={renderEmbedded}
      />
    );

    if (renderEmbedded) {
      return content;
    }

    return (
      <PrettyCard label={label} depth={depth}>
        {content}
      </PrettyCard>
    );
  }

  return (
    <PrettyCard
      label={label}
      depth={depth}
      actions={actions}
      onEdit={onJumpToEdit ? () => onJumpToEdit(path) : undefined}
      editDisabled={editDisabled}
      editTitle={editTitle}
    >
      {externalUrl ? (
        <UrlValue value={expanded ? value : getStringPreview(value)} href={externalUrl} />
      ) : (
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
      )}
    </PrettyCard>
  );
}

function PrettyArrayValue({
  label,
  value,
  depth,
  path,
  onJumpToEdit,
  onReplaceDocument,
  editDisabled,
  editTitle,
  onOpenDocument,
  suppressHeader = false,
}: {
  label: string | null;
  value: unknown[];
  depth: number;
  path: JsonPath;
  onJumpToEdit?: (path: JsonPath) => void;
  onReplaceDocument?: (path: JsonPath, doc: DetectedDocument) => void;
  editDisabled?: boolean;
  editTitle?: string;
  onOpenDocument: (doc: DetectedDocument) => void;
  suppressHeader?: boolean;
}) {
  const [expanded, setExpanded] = useState(true);
  const detectedMessages = detectMessageLikeArray(value);
  const columns = getUniformObjectArrayColumns(value);
  const singleItem = value[0];
  const hasOuterShell = !(suppressHeader && label === null);

  let content: React.ReactNode;
  if (!expanded) {
    content = <div style={{ color: "var(--color-text-muted)", fontSize: "13px" }}>{`${value.length} items`}</div>;
  } else if (value.length === 0) {
    content = <div style={{ color: "var(--color-text-muted)", fontSize: "13px" }}>Empty array</div>;
  } else if (detectedMessages) {
    content = value.length === 1 ? (
      <div style={{ display: "grid", gap: "8px" }}>
        <MessageBubbleBody
          value={detectedMessages[0].content}
          depth={depth + 1}
          path={[...path, "0", ...detectedMessages[0].contentPath]}
          onJumpToEdit={onJumpToEdit}
          onReplaceDocument={onReplaceDocument}
          editDisabled={editDisabled}
          editTitle={editTitle}
          onOpenDocument={onOpenDocument}
          suppressArrayHeader
          suppressNestedShell
        />
        <MessageMetadataStrip metadata={detectedMessages[0].metadata} />
      </div>
    ) : (
      <div style={{ display: "grid", gap: "10px" }}>
        {detectedMessages.map((message, index) => (
          <ArrayItemBox
            key={`message-${index}`}
            headerAddon={<MessageRolePill roleStyle={message.roleStyle} />}
          >
            <div style={{ display: "grid", gap: "8px" }}>
              <MessageBubbleBody
                value={message.content}
                depth={depth + 1}
                path={[...path, String(index), ...message.contentPath]}
                onJumpToEdit={onJumpToEdit}
                onReplaceDocument={onReplaceDocument}
                editDisabled={editDisabled}
                editTitle={editTitle}
                onOpenDocument={onOpenDocument}
                suppressArrayHeader
                suppressNestedShell
              />
              <MessageMetadataStrip metadata={message.metadata} />
            </div>
          </ArrayItemBox>
        ))}
      </div>
    );
  } else if (value.length === 1) {
    content = (
      <PrettyValue
        label={null}
        value={singleItem}
        depth={depth + 1}
        path={[...path, "0"]}
        siblingData={isRecord(singleItem) ? singleItem : undefined}
        onJumpToEdit={onJumpToEdit}
        onReplaceDocument={onReplaceDocument}
        editDisabled={editDisabled}
        editTitle={editTitle}
        onOpenDocument={onOpenDocument}
        suppressArrayHeader={suppressHeader}
        suppressNestedShell={hasOuterShell}
      />
    );
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
            <InlineArrayItemRow
              key={`array-${index}`}
              value={item}
              onEdit={onJumpToEdit ? () => onJumpToEdit([...path, String(index)]) : undefined}
              editDisabled={editDisabled}
              editTitle={editTitle}
            />
          ) : (
            <ArrayItemBox
              key={`array-${index}`}
            >
              <PrettyValue
                label={null}
                value={item}
                depth={depth + 1}
                path={[...path, String(index)]}
                siblingData={isRecord(item) ? item : undefined}
                onJumpToEdit={onJumpToEdit}
                onReplaceDocument={onReplaceDocument}
                editDisabled={editDisabled}
                editTitle={editTitle}
                onOpenDocument={onOpenDocument}
                suppressArrayHeader={suppressHeader}
              />
            </ArrayItemBox>
          )
        ))}
      </div>
    );
  }

  if (suppressHeader && label === null) {
    return <>{content}</>;
  }

  return (
    <PrettyCard
      label={label}
      badge={`list · ${value.length}`}
      headerAddon={detectedMessages && value.length === 1 ? <MessageRolePill roleStyle={detectedMessages[0].roleStyle} /> : undefined}
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
  path,
  onJumpToEdit,
  onReplaceDocument,
  editDisabled,
  editTitle,
  onOpenDocument,
}: {
  label: string | null;
  value: Record<string, unknown>;
  depth: number;
  path: JsonPath;
  onJumpToEdit?: (path: JsonPath) => void;
  onReplaceDocument?: (path: JsonPath, doc: DetectedDocument) => void;
  editDisabled?: boolean;
  editTitle?: string;
  onOpenDocument: (doc: DetectedDocument) => void;
}) {
  const detectedMessage = detectMessageLikeObject(value);
  const flattenedGroups = detectFlattenedMessageGroups(value);
  const groupByMessageKey = new Map(flattenedGroups.map((group) => [group.messageKey, group]));
  const consumedKeys = new Set(flattenedGroups.flatMap((group) => group.consumedKeys));
  if (detectedMessage) {
    const contentBadge = Array.isArray(detectedMessage.content) ? `list · ${detectedMessage.content.length}` : undefined;
    return (
      <PrettyCard
        label={label}
        badge={contentBadge}
        headerAddon={<MessageRolePill roleStyle={detectedMessage.roleStyle} />}
        depth={depth}
      >
        <MessageBubbleBody
          value={detectedMessage.content}
          depth={depth + 1}
          path={[...path, ...detectedMessage.contentPath]}
          onJumpToEdit={onJumpToEdit}
          onReplaceDocument={onReplaceDocument}
          editDisabled={editDisabled}
          editTitle={editTitle}
          onOpenDocument={onOpenDocument}
          suppressArrayHeader
          suppressNestedShell
        />
        <MessageMetadataStrip metadata={detectedMessage.metadata} />
      </PrettyCard>
    );
  }

  const entries = Object.entries(value);
  const content = (
    <div style={{ display: "grid", gap: "10px" }}>
      {entries.map(([childKey, childValue]) => {
        const group = groupByMessageKey.get(childKey);
        if (group) {
          return (
            <FlattenedMessageGroupCard
              key={childKey}
              group={group}
              depth={depth + 1}
              onJumpToEdit={onJumpToEdit}
              onReplaceDocument={onReplaceDocument}
              editDisabled={editDisabled}
              editTitle={editTitle}
              onOpenDocument={onOpenDocument}
            />
          );
        }

        if (consumedKeys.has(childKey)) {
          return null;
        }

        return isInlineSimpleValue(childValue, value) ? (
          <InlineValueRow
            key={childKey}
            label={childKey}
            value={childValue}
            onEdit={onJumpToEdit ? () => onJumpToEdit([...path, childKey]) : undefined}
            editDisabled={editDisabled}
            editTitle={editTitle}
          />
        ) : (
          <PrettyValue
            key={childKey}
            label={childKey}
            value={childValue}
            depth={depth + 1}
            path={[...path, childKey]}
            siblingData={value}
            onJumpToEdit={onJumpToEdit}
            onReplaceDocument={onReplaceDocument}
            editDisabled={editDisabled}
            editTitle={editTitle}
            onOpenDocument={onOpenDocument}
          />
        );
      })}
    </div>
  );

  if (label === null) {
    return content;
  }

  return (
    <PrettyCard
      label={label}
      badge={`object · ${entries.length}`}
      depth={depth}
    >
      {entries.length > 0 ? content : <div style={{ color: "var(--color-text-muted)", fontSize: "13px" }}>Empty object</div>}
    </PrettyCard>
  );
}

function PrettyValue({
  label,
  value,
  depth,
  path,
  siblingData,
  onJumpToEdit,
  onReplaceDocument,
  editDisabled,
  editTitle,
  onOpenDocument,
  suppressArrayHeader = false,
  suppressNestedShell = false,
}: {
  label: string | null;
  value: unknown;
  depth: number;
  path: JsonPath;
  siblingData?: Record<string, unknown>;
  onJumpToEdit?: (path: JsonPath) => void;
  onReplaceDocument?: (path: JsonPath, doc: DetectedDocument) => void;
  editDisabled?: boolean;
  editTitle?: string;
  onOpenDocument: (doc: DetectedDocument) => void;
  suppressArrayHeader?: boolean;
  suppressNestedShell?: boolean;
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
    return (
      <ScalarBox
        label={label}
        value={value}
        depth={depth}
        onEdit={onJumpToEdit && path.length > 0 ? () => onJumpToEdit(path) : undefined}
        editDisabled={editDisabled}
        editTitle={editTitle}
      />
    );
  }

  if (typeof value === "string") {
    return (
      <PrettyStringValue
        label={label}
        value={value}
        depth={depth}
        path={path}
        siblingData={siblingData}
        onJumpToEdit={onJumpToEdit}
        onReplaceDocument={onReplaceDocument}
        editDisabled={editDisabled}
        editTitle={editTitle}
        onOpenDocument={onOpenDocument}
        suppressNestedShell={suppressNestedShell}
      />
    );
  }

  if (Array.isArray(value)) {
    return (
      <PrettyArrayValue
        label={label}
        value={value}
        depth={depth}
        path={path}
        onJumpToEdit={onJumpToEdit}
        onReplaceDocument={onReplaceDocument}
        editDisabled={editDisabled}
        editTitle={editTitle}
        onOpenDocument={onOpenDocument}
        suppressHeader={suppressArrayHeader}
      />
    );
  }

  if (isRecord(value)) {
    return (
      <PrettyObjectValue
        label={label}
        value={value}
        depth={depth}
        path={path}
        onJumpToEdit={onJumpToEdit}
        onReplaceDocument={onReplaceDocument}
        editDisabled={editDisabled}
        editTitle={editTitle}
        onOpenDocument={onOpenDocument}
      />
    );
  }

  return (
    <ScalarBox
      label={label}
      value={String(value)}
      depth={depth}
      onEdit={onJumpToEdit && path.length > 0 ? () => onJumpToEdit(path) : undefined}
      editDisabled={editDisabled}
      editTitle={editTitle}
    />
  );
}

function PrettyContent({
  data,
  onJumpToEdit,
  onReplaceDocument,
  editDisabled,
  editTitle,
  onOpenDocument,
}: {
  data: Record<string, unknown>;
  onJumpToEdit?: (path: JsonPath) => void;
  onReplaceDocument?: (path: JsonPath, doc: DetectedDocument) => void;
  editDisabled?: boolean;
  editTitle?: string;
  onOpenDocument: (doc: DetectedDocument) => void;
}) {
  return (
    <div className="io-pretty-content">
      <PrettyValue
        label={null}
        value={data}
        depth={0}
        path={[]}
        siblingData={data}
        onJumpToEdit={onJumpToEdit}
        onReplaceDocument={onReplaceDocument}
        editDisabled={editDisabled}
        editTitle={editTitle}
        onOpenDocument={onOpenDocument}
      />
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
  const jsonStr = useMemo(() => stringifyJsonWithOffset(data, null).text, [data]);
  const [editValue, setEditValue] = useState("");
  const [prettyDraftData, setPrettyDraftData] = useState<Record<string, unknown> | null>(null);
  const [editPresentation, setEditPresentation] = useState<"raw" | "pretty">("raw");
  const [ghost, setGhost] = useState("");
  const [pendingJumpTarget, setPendingJumpTarget] = useState<JumpTarget | null>(null);
  const [previewAttachment, setPreviewAttachment] = useState<Attachment | null>(null);
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);
  const ghostTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const selectionRestoreTimerRef = useRef<number | null>(null);

  const myKey: EditKey = `${nodeId}:${label as "Input" | "Output"}`;
  const isActiveEdit = editLock === myKey;
  const isLocked = (editLock !== null && !isActiveEdit) || (hasAnyEdit && !isEdited);
  const editTitle = isLocked ? "Finish the current edit before editing another field" : `Edit ${label.toLowerCase()} field`;
  const displayData = isActiveEdit && editPresentation === "pretty" && prettyDraftData ? prettyDraftData : data;
  const attachments = useMemo(() => extractAttachments(displayData), [displayData]);
  const currentEditJson = useMemo(() => {
    if (!isActiveEdit) {
      return "";
    }

    if (editPresentation === "pretty") {
      return stringifyJsonWithOffset(prettyDraftData ?? data, null).text;
    }

    return editValue;
  }, [data, editPresentation, editValue, isActiveEdit, prettyDraftData]);
  const hasMeaningfulDiff = useMemo(() => {
    if (!isActiveEdit) {
      return false;
    }

    return normalizeJsonText(currentEditJson) !== normalizeJsonText(jsonStr);
  }, [currentEditJson, isActiveEdit, jsonStr]);
  const handleOpenDocument = useCallback((doc: DetectedDocument) => {
    if (isPreviewableDocument(doc)) {
      setPreviewAttachment({
        id: `preview-${doc.data.slice(0, 24)}`,
        name: doc.name || "document",
        mimeType: doc.mimeType,
        data: doc.data,
      });
      return;
    }

    void saveDocument(doc);
  }, []);

  const handleReplaceDocument = useCallback(async (path: JsonPath, doc: DetectedDocument) => {
    if (!nodeId || isLocked || doc.type === "unknown") {
      return;
    }

    const replacement = await pickReplacementDocumentFromBrowser(doc.type);
    if (!replacement) {
      return;
    }

    let sourceData: unknown = data;
    if (isActiveEdit && editPresentation === "pretty" && prettyDraftData) {
      sourceData = prettyDraftData;
    } else if (isActiveEdit) {
      try {
        sourceData = JSON.parse(editValue);
      } catch {
        return;
      }
    }

    try {
      const updatedData = applyDocumentReplacement(sourceData, path, replacement) as Record<string, unknown>;
      const nextJson = stringifyJsonWithOffset(updatedData, null).text;
      setPendingJumpTarget(null);
      setGhost("");
      setPrettyDraftData(updatedData);
      setEditPresentation("pretty");

      if (!isActiveEdit) {
        onStartEdit(nodeId, label as "Input" | "Output");
      }
      setEditValue(nextJson);
    } catch (error) {
      console.warn("[RunTraceFlow] Failed to replace document", error);
    }
  }, [data, editPresentation, editValue, isActiveEdit, isLocked, label, nodeId, onStartEdit, prettyDraftData]);

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

  const clearSelectionRestoreTimer = useCallback(() => {
    if (selectionRestoreTimerRef.current !== null) {
      window.clearTimeout(selectionRestoreTimerRef.current);
      selectionRestoreTimerRef.current = null;
    }
  }, []);

  const resizeEditTextarea = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }

    textarea.style.height = "auto";
    const maxHeight = Math.max(260, Math.floor(window.innerHeight * 0.72));
    textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
  }, []);

  const handleEditChange = useCallback((event: React.ChangeEvent<HTMLTextAreaElement>) => {
    clearSelectionRestoreTimer();
    const value = event.target.value;
    setEditValue(value);
    generateGhost(value);
  }, [clearSelectionRestoreTimer, generateGhost]);

  const requestCloseEdit = useCallback(() => {
    clearSelectionRestoreTimer();
    setGhost("");
    if (hasMeaningfulDiff) {
      setShowCloseConfirm(true);
      return;
    }

    setShowCloseConfirm(false);
    setEditValue("");
    setPrettyDraftData(null);
    setEditPresentation("raw");
    setPendingJumpTarget(null);
    onCancelEdit();
  }, [clearSelectionRestoreTimer, hasMeaningfulDiff, onCancelEdit]);

  const handleEditKeyDown = useCallback((event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    clearSelectionRestoreTimer();
    if (event.key === "Escape") {
      event.preventDefault();
      requestCloseEdit();
      return;
    }
    if (event.key === "Tab" && ghost) {
      event.preventDefault();
      const nextValue = editValue + ghost;
      setEditValue(nextValue);
      setGhost("");
      generateGhost(nextValue);
    }
  }, [clearSelectionRestoreTimer, editValue, generateGhost, ghost, requestCloseEdit]);

  const startEdit = useCallback(() => {
    if (!nodeId || isLocked) return;
    setEditValue(jsonStr);
    setPrettyDraftData(null);
    setEditPresentation("raw");
    setPendingJumpTarget(null);
    setShowCloseConfirm(false);
    setGhost("");
    onStartEdit(nodeId, label as "Input" | "Output");
  }, [isLocked, jsonStr, label, nodeId, onStartEdit]);

  const jumpToEdit = useCallback((path: JsonPath) => {
    if (!nodeId || isLocked) return;
    const sourceData = isActiveEdit && editPresentation === "pretty" && prettyDraftData ? prettyDraftData : data;
    setPendingJumpTarget({ path, cursorOffset: getSelectionLeafOffset(), selectedText: getSelectionLeafText() });
    setShowCloseConfirm(false);
    setGhost("");
    setEditValue(stringifyJsonWithOffset(sourceData, path).text);
    setEditPresentation("raw");
    if (!isActiveEdit) {
      onStartEdit(nodeId, label as "Input" | "Output");
    }
  }, [data, editPresentation, isActiveEdit, isLocked, label, nodeId, onStartEdit, prettyDraftData]);

  const cancelEdit = useCallback(() => {
    setEditValue("");
    setPrettyDraftData(null);
    setEditPresentation("raw");
    setPendingJumpTarget(null);
    setShowCloseConfirm(false);
    setGhost("");
    onCancelEdit();
  }, [onCancelEdit]);

  const saveEdit = useCallback(() => {
    if (nodeId && hasMeaningfulDiff) {
      onSaveEdit(nodeId, label as "Input" | "Output", currentEditJson);
      setPrettyDraftData(null);
      setEditPresentation("raw");
      setShowCloseConfirm(false);
    }
  }, [currentEditJson, hasMeaningfulDiff, label, nodeId, onSaveEdit]);

  const saveAndRerun = useCallback(() => {
    if (nodeId && hasMeaningfulDiff) {
      onSaveAndRerun(nodeId, label as "Input" | "Output", currentEditJson);
      setPrettyDraftData(null);
      setEditPresentation("raw");
      setShowCloseConfirm(false);
    }
  }, [currentEditJson, hasMeaningfulDiff, label, nodeId, onSaveAndRerun]);

  const switchToRawEdit = useCallback(() => {
    setEditValue(currentEditJson);
    setEditPresentation("raw");
    setPendingJumpTarget(null);
    setShowCloseConfirm(false);
    setGhost("");
  }, [currentEditJson]);

  const focusEditorAtPath = useCallback((target: JumpTarget) => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }

    clearSelectionRestoreTimer();
    resizeEditTextarea();

    requestAnimationFrame(() => {
      const activeTextarea = textareaRef.current;
      if (!activeTextarea) {
        return;
      }

      const sourceData = isActiveEdit && editPresentation === "pretty" && prettyDraftData ? prettyDraftData : data;
      const { offset } = stringifyJsonWithOffset(sourceData, target.path, target.cursorOffset);
      const { start, end, caret } = getTransientSelectionRange(activeTextarea.value, offset, target.selectedText);

      activeTextarea.focus();
      activeTextarea.setSelectionRange(start, end);
      scrollTextareaOffsetIntoView(activeTextarea, caret);

      if (start !== end) {
        const initialSelectionStart = start;
        const initialSelectionEnd = end;
        selectionRestoreTimerRef.current = window.setTimeout(() => {
          if (document.activeElement !== activeTextarea) {
            selectionRestoreTimerRef.current = null;
            return;
          }

          if (activeTextarea.selectionStart !== initialSelectionStart || activeTextarea.selectionEnd !== initialSelectionEnd) {
            selectionRestoreTimerRef.current = null;
            return;
          }

          activeTextarea.setSelectionRange(caret, caret);
          selectionRestoreTimerRef.current = null;
        }, 900);
      }
    });
  }, [clearSelectionRestoreTimer, data, editPresentation, isActiveEdit, prettyDraftData, resizeEditTextarea]);

  useEffect(() => {
    if (!isActiveEdit || !pendingJumpTarget) {
      return;
    }

    const frame = requestAnimationFrame(() => {
      focusEditorAtPath(pendingJumpTarget);
      setPendingJumpTarget(null);
    });

    return () => cancelAnimationFrame(frame);
  }, [focusEditorAtPath, isActiveEdit, pendingJumpTarget]);

  useEffect(() => {
    return () => {
      clearSelectionRestoreTimer();
    };
  }, [clearSelectionRestoreTimer]);

  useEffect(() => {
    if (!isActiveEdit && !showCloseConfirm) {
      return;
    }

    const handleWindowKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }

      event.preventDefault();
      if (showCloseConfirm) {
        setShowCloseConfirm(false);
        return;
      }

      if (isActiveEdit) {
        requestCloseEdit();
      }
    };

    window.addEventListener("keydown", handleWindowKeyDown);
    return () => window.removeEventListener("keydown", handleWindowKeyDown);
  }, [isActiveEdit, requestCloseEdit, showCloseConfirm]);

  useEffect(() => {
    if (!isActiveEdit || editPresentation !== "raw") {
      return;
    }

    const frame = requestAnimationFrame(() => {
      resizeEditTextarea();
    });

    return () => cancelAnimationFrame(frame);
  }, [editPresentation, editValue, isActiveEdit, resizeEditTextarea]);

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
          {isActiveEdit && editPresentation === "pretty" && (
            <button className="io-edit-btn" onClick={switchToRawEdit}>
              <Pencil size={11} /> Edit JSON
            </button>
          )}
        </div>
      </div>
      <div className="io-panel-content">
        {isActiveEdit && editPresentation === "raw" ? (
          <div className="io-edit-area">
            <div className="io-edit-wrapper">
              <div className="io-edit-ghost" aria-hidden>
                <span style={{ color: "transparent" }}>{editValue}</span>
                {ghost && <span className="io-edit-ghost-suggestion">{ghost}</span>}
              </div>
              <textarea
                ref={textareaRef}
                className="io-edit-textarea"
                value={editValue}
                onChange={handleEditChange}
                onKeyDown={handleEditKeyDown}
                onMouseDown={clearSelectionRestoreTimer}
                spellCheck={false}
                style={{ background: "transparent", position: "relative", zIndex: 1 }}
              />
              {ghost && <span className="io-edit-ghost-hint">Tab to accept</span>}
            </div>
            <div className="io-edit-toolbar">
              <button className="io-edit-save-rerun" onClick={saveAndRerun} disabled={!hasMeaningfulDiff}>Save and Rerun</button>
              <button className="io-edit-save" onClick={saveEdit} disabled={!hasMeaningfulDiff}>Save</button>
              <button className="io-edit-cancel" onClick={requestCloseEdit}>Cancel</button>
            </div>
          </div>
        ) : !isActiveEdit && viewMode === "json" ? (
          <CodeBlock code={jsonStr} language="json" />
        ) : (
          <>
            <PrettyContent
              data={displayData}
              onJumpToEdit={jumpToEdit}
              onReplaceDocument={handleReplaceDocument}
              editDisabled={isLocked}
              editTitle={editTitle}
              onOpenDocument={handleOpenDocument}
            />
            {isActiveEdit && (
              <div className="io-edit-toolbar">
                <button className="io-edit-save-rerun" onClick={saveAndRerun} disabled={!hasMeaningfulDiff}>Save and Rerun</button>
                <button className="io-edit-save" onClick={saveEdit} disabled={!hasMeaningfulDiff}>Save</button>
                <button className="io-edit-cancel" onClick={requestCloseEdit}>Cancel</button>
              </div>
            )}
          </>
        )}
        {attachments.length > 0 && (
          <>
            <div className="io-attachments-header">Files in this message</div>
            <AttachmentStrip attachments={attachments} />
          </>
        )}
        {previewAttachment && (
          <DocumentPreviewModal
            attachment={previewAttachment}
            onClose={() => setPreviewAttachment(null)}
          />
        )}
        {showCloseConfirm && (
          <div className="modal-overlay" onClick={() => setShowCloseConfirm(false)}>
            <div className="modal io-exit-modal" onClick={(event) => event.stopPropagation()}>
              <div className="modal-header">
                <h2 className="modal-title">Unsaved changes</h2>
                <button className="modal-close" onClick={() => setShowCloseConfirm(false)}>✕</button>
              </div>
              <p className="modal-subtitle">Choose how to leave this edit.</p>
              <div className="modal-actions">
                <button className="io-edit-save-rerun" onClick={saveAndRerun}>Save and Rerun</button>
                <button className="io-edit-save" onClick={saveEdit}>Save</button>
                <button className="io-edit-cancel" onClick={cancelEdit}>Close</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function NodeHeader({ node }: { node: GraphNode }) {
  const displayId = node.step_id || node.id;
  const [copied, setCopied] = useState(false);

  const handleCopyId = useCallback(() => {
    navigator.clipboard.writeText(displayId);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [displayId]);

  return (
    <div className="node-card-header">
      <div className="node-card-title-row">
        <span className="node-card-name">{node.label}</span>
      </div>
      <div className="node-card-meta-row">
        {node.model && <span className="node-card-type llm">{node.model}</span>}
        <span className="node-card-id" title={displayId}>
          {displayId}
          <button className="node-card-id-copy" onClick={handleCopyId} title="Copy step ID">
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
