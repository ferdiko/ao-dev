import { useState, useCallback, useMemo, useRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { AttachmentStrip } from "./AttachmentPreview";
import { extractAttachments } from "../attachmentUtils";
import { Sparkles, Pencil, Loader2, Copy } from "lucide-react";
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
  'code[class*="language-"]': { color: "#2c2c2c", fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace', fontSize: "12.5px", lineHeight: "1.6" },
  'pre[class*="language-"]': { background: "transparent", margin: 0, padding: 0, overflow: "auto" },
  comment: { color: "#8a8a7e" },
  string: { color: "#43884e" },
  number: { color: "#b45309" },
  boolean: { color: "#b45309" },
  keyword: { color: "#7c3aed" },
  punctuation: { color: "#8a8a7e" },
  property: { color: "#5a5a52" },
  operator: { color: "#8a8a7e" },
  "attr-name": { color: "#5a5a52" },
  function: { color: "#6f42c1" },
  builtin: { color: "#6f42c1" },
  "class-name": { color: "#b45309" },
};

const LANG_PATTERNS: [RegExp, string][] = [
  [/^\s*SELECT\b|^\s*INSERT\b|^\s*UPDATE\b|^\s*DELETE\b|^\s*CREATE\b|^\s*ALTER\b|^\s*DROP\b|^\s*WITH\b.*\bAS\b/im, "sql"],
  [/^\s*\{[\s\S]*"[^"]+"\s*:/m, "json"],
  [/^\s*\[[\s\S]*\{[\s\S]*"[^"]+"\s*:/m, "json"],
  [/^\s*(def |import |from |class \w+[:(]|if __name__)/m, "python"],
  [/^\s*(fn |let mut |use |pub |impl |struct |enum .*\{|mod )/m, "rust"],
  [/^\s*(const |let |var |function |import .* from |export |=>\s*\{)/m, "javascript"],
  [/^\s*(interface |type \w+ =|:\s*(string|number|boolean))/m, "typescript"],
  [/^\s*(package |func |import \(|fmt\.|go\s+\w+)/m, "go"],
  [/^\s*<[a-zA-Z][\s\S]*>/m, "html"],
  [/^\s*(#!\s*\/|^\s*\$\s+\w|^\s*(echo|curl|grep|awk|sed|cat|ls|cd|mkdir)\b)/m, "bash"],
];

function detectLanguage(text: string): string | null {
  const trimmed = text.trim();
  if (!trimmed || trimmed.length < 8) return null;
  for (const [pattern, lang] of LANG_PATTERNS) {
    if (pattern.test(trimmed)) return lang;
  }
  return null;
}

const LANG_DISPLAY: Record<string, string> = {
  sql: "SQL",
  json: "JSON",
  python: "Python",
  rust: "Rust",
  javascript: "JavaScript",
  typescript: "TypeScript",
  go: "Go",
  html: "HTML",
  bash: "Bash",
  css: "CSS",
  yaml: "YAML",
  xml: "XML",
};

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
        customStyle={{ background: "transparent", padding: "12px 14px", margin: 0, fontSize: "12.5px" }}
        wrapLongLines
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}

type PrettyBlock =
  | { type: "label"; label: string }
  | { type: "markdown"; content: string }
  | { type: "code"; code: string; language: string }
  | { type: "separator" };

function addContentBlocks(content: string, blocks: PrettyBlock[]) {
  const parts = content.split(/(```\w*\n[\s\S]*?```)/g);
  for (const part of parts) {
    const fenceMatch = part.match(/^```(\w*)\n([\s\S]*?)```$/);
    if (fenceMatch) {
      const lang = fenceMatch[1] || detectLanguage(fenceMatch[2]) || "text";
      blocks.push({ type: "code", code: fenceMatch[2].replace(/\n$/, ""), language: lang });
    } else if (part.trim()) {
      const detected = detectLanguage(part.trim());
      if (detected) {
        blocks.push({ type: "code", code: part.trim(), language: detected });
      } else {
        blocks.push({ type: "markdown", content: part });
      }
    }
  }
}

function extractPrettyBlocks(data: Record<string, unknown>): PrettyBlock[] {
  const blocks: PrettyBlock[] = [];

  const messages = data.messages as Array<{ role: string; content: string | Array<{ type: string; text?: string }> }> | undefined;
  if (messages) {
    messages.forEach((message, index) => {
      if (index > 0) blocks.push({ type: "separator" });
      blocks.push({ type: "label", label: message.role });
      if (typeof message.content === "string") {
        addContentBlocks(message.content, blocks);
      } else if (Array.isArray(message.content)) {
        for (const part of message.content) {
          if (part.type === "text" && part.text) addContentBlocks(part.text, blocks);
        }
      }
    });
    return blocks;
  }

  const choices = data.choices as Array<{ message: { role: string; content: string } }> | undefined;
  if (choices) {
    choices.forEach((choice, index) => {
      if (index > 0) blocks.push({ type: "separator" });
      if (choice.message?.role) blocks.push({ type: "label", label: choice.message.role });
      if (choice.message?.content) addContentBlocks(choice.message.content, blocks);
    });
    return blocks;
  }

  const entries = Object.entries(data);
  if (entries.length > 0 && entries.every(([key]) => typeof key === "string")) {
    for (const [key, value] of entries) {
      if (value === null || value === undefined) continue;
      blocks.push({ type: "label", label: key });
      if (typeof value === "string") {
        addContentBlocks(value, blocks);
      } else {
        blocks.push({ type: "code", code: JSON.stringify(value, null, 2), language: "json" });
      }
    }
    if (blocks.length > 0) return blocks;
  }

  blocks.push({ type: "code", code: JSON.stringify(data, null, 2), language: "json" });
  return blocks;
}

function MarkdownContent({ markdown }: { markdown: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || "");
          const codeStr = String(children).replace(/\n$/, "");
          if (match) {
            return <CodeBlock code={codeStr} language={match[1]} />;
          }
          return <code className="io-inline-code" {...props}>{children}</code>;
        },
      }}
    >
      {markdown}
    </Markdown>
  );
}

function PrettyContent({ data }: { data: Record<string, unknown> }) {
  const blocks = useMemo(() => extractPrettyBlocks(data), [data]);

  return (
    <div className="io-pretty-content">
      {blocks.map((block, index) => {
        switch (block.type) {
          case "label":
            return <div key={index} className="io-role-label">{block.label}</div>;
          case "markdown":
            return <div key={index}><MarkdownContent markdown={block.content} /></div>;
          case "code":
            return <CodeBlock key={index} code={block.code} language={block.language} />;
          case "separator":
            return <hr key={index} className="io-separator" />;
          default:
            return null;
        }
      })}
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
    <div className={`io-panel${isEdited ? " io-panel-edited" : ""}`}>
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
          <PrettyContent data={data} />
        )}
        <AttachmentStrip attachments={attachments} />
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
            onClick={() => onCardClick(node.id)}
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
