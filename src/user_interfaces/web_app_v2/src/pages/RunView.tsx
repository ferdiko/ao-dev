import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { useParams } from "react-router-dom";
import {
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Node,
  type Edge,
  type NodeTypes,
  type NodeProps,
  type EdgeProps,
  type EdgeTypes,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { Breadcrumb } from "../components/Breadcrumb";
import { AttachmentStrip, extractAttachments } from "../components/AttachmentPreview";
import {
  fetchProject, fetchGraph, fetchExperimentDetail,
  editInput, editOutput, restartRun, eraseRun, updateResult,
  type BackendGraphNode, type BackendGraphEdge, type GraphPayload,
} from "../api";
import { subscribe } from "../serverEvents";
import { layoutGraph, NODE_W, NODE_H, type Point } from "../graphLayout";
import { Sparkles, Pencil, RotateCcw, Loader2, Undo2, ThumbsUp, ThumbsDown, Copy } from "lucide-react";

// ── Types ────────────────────────────────────────────────

/** Frontend graph node with parsed input/output objects. */
interface GraphNode {
  id: string;
  label: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  border_color?: string;
  stack_trace?: string;
  model?: string;
  attachments?: unknown[];
}

interface GraphEdge {
  id: string;
  source: string;
  target: string;
}

/** Parse backend graph payload into frontend types.
 *  Graph nodes contain to_show data directly (display-ready). */
function parseGraphPayload(payload: GraphPayload): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = payload.nodes.map((n: BackendGraphNode) => {
    let input: Record<string, unknown> = {};
    let output: Record<string, unknown> = {};
    try { input = typeof n.input === "string" ? JSON.parse(n.input) : (n.input as any) ?? {}; } catch { /* empty */ }
    try { output = typeof n.output === "string" ? JSON.parse(n.output) : (n.output as any) ?? {}; } catch { /* empty */ }
    return {
      id: n.id, label: n.label,
      input,
      output,
      border_color: n.border_color, stack_trace: n.stack_trace, model: n.model, attachments: n.attachments,
    };
  });
  const edges: GraphEdge[] = payload.edges.map((e: BackendGraphEdge) => ({
    id: e.id, source: e.source, target: e.target,
  }));
  return { nodes, edges };
}

// topoSortNodes is used by FullTraceFlow for the detail panel ordering
function topoSortNodes(graphNodes: GraphNode[], graphEdges: GraphEdge[]): GraphNode[] {
  const inDeg = new Map<string, number>();
  const children = new Map<string, string[]>();
  for (const n of graphNodes) { inDeg.set(n.id, 0); children.set(n.id, []); }
  for (const e of graphEdges) {
    inDeg.set(e.target, (inDeg.get(e.target) ?? 0) + 1);
    children.get(e.source)?.push(e.target);
  }
  const queue = graphNodes.filter((n) => (inDeg.get(n.id) ?? 0) === 0).map((n) => n.id);
  const order: string[] = [];
  let i = 0;
  while (i < queue.length) {
    const id = queue[i++];
    order.push(id);
    for (const childId of children.get(id) ?? []) {
      inDeg.set(childId, (inDeg.get(childId) ?? 0) - 1);
      if (inDeg.get(childId) === 0) queue.push(childId);
    }
  }
  const idToNode = new Map(graphNodes.map((n) => [n.id, n]));
  return order.map((id) => idToNode.get(id)!).filter(Boolean);
}

// ── Custom LLM Node ────────────────────────────────────

function LLMNode({ data, selected }: NodeProps) {
  const d = data as { label: string; model?: string; nodeId: string; focused?: boolean; borderColor?: string };
  return (
    <div
      className={`graph-llm-node${selected ? " selected" : ""}${d.focused ? " focused" : ""}`}
      style={d.focused ? { borderColor: "#43884e" } : undefined}
    >
      <Handle type="target" position={Position.Top} id="top" className="graph-handle" />
      <Handle type="target" position={Position.Left} id="left" className="graph-handle graph-handle-side" />
      <Handle type="target" position={Position.Right} id="right" className="graph-handle graph-handle-side" />
      <div className="graph-node-label">{d.label}</div>
      {d.model && <div className="graph-node-model">{d.model}</div>}
      <Handle type="source" position={Position.Bottom} id="bottom" className="graph-handle" />
      <Handle type="source" position={Position.Left} id="left" className="graph-handle graph-handle-side" />
      <Handle type="source" position={Position.Right} id="right" className="graph-handle graph-handle-side" />
    </div>
  );
}

/** Custom edge that renders a polyline path from layout engine waypoints. */
function RoutedEdgeComponent({ id, data }: EdgeProps) {
  const d_ = data as Record<string, unknown>;
  const points = d_?.points as Point[] | undefined;
  const highlighted = d_?.highlighted as boolean;
  const color = highlighted ? "#43884e" : "var(--color-text-muted)";
  const strokeWidth = highlighted ? 2.5 : 1.5;
  if (!points || points.length < 2) return null;
  const d = points.reduce((acc, p, i) =>
    i === 0 ? `M ${p.x},${p.y}` : `${acc} L ${p.x},${p.y}`, "");
  const markerId = `arrow-${id}`;
  return (
    <>
      <defs>
        <marker id={markerId} markerWidth="8" markerHeight="8" refX="6" refY="4"
          orient="auto" markerUnits="userSpaceOnUse">
          <polygon points="0,0 8,4 0,8" fill={color} />
        </marker>
      </defs>
      <path d={d} markerEnd={`url(#${markerId})`}
        style={{ stroke: color, strokeWidth, fill: "none" }} />
    </>
  );
}

const nodeTypes: NodeTypes = { llmNode: LLMNode };
const edgeTypes: EdgeTypes = { routed: RoutedEdgeComponent };

// ── Syntax theme (warm minimal) ─────────────────────────

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

// ── Language detection ──────────────────────────────────

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
  sql: "SQL", json: "JSON", python: "Python", rust: "Rust",
  javascript: "JavaScript", typescript: "TypeScript", go: "Go",
  html: "HTML", bash: "Bash", css: "CSS", yaml: "YAML", xml: "XML",
};

// ── Code Block with language label + copy button ────────

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

// ── I/O Detail Panel ───────────────────────────────────

type ViewMode = "pretty" | "json";

type PrettyBlock = { type: "label"; label: string } | { type: "markdown"; content: string } | { type: "code"; code: string; language: string } | { type: "separator" };

/** Split a string into markdown and fenced code blocks. */
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

/** Extract structured content from LLM I/O data for pretty rendering.
 *  Handles both flattened `to_show` format (dot-separated keys) and
 *  nested formats (messages array, choices array). */
function extractPrettyBlocks(data: Record<string, unknown>): PrettyBlock[] {
  const blocks: PrettyBlock[] = [];

  // Chat messages format (nested input)
  const messages = data.messages as Array<{ role: string; content: string | Array<{ type: string; text?: string }> }> | undefined;
  if (messages) {
    messages.forEach((m, i) => {
      if (i > 0) blocks.push({ type: "separator" });
      blocks.push({ type: "label", label: m.role });
      if (typeof m.content === "string") {
        addContentBlocks(m.content, blocks);
      } else if (Array.isArray(m.content)) {
        for (const part of m.content) {
          if (part.type === "text" && part.text) addContentBlocks(part.text, blocks);
        }
      }
    });
    return blocks;
  }

  // Chat choices format (nested output)
  const choices = data.choices as Array<{ message: { role: string; content: string } }> | undefined;
  if (choices) {
    choices.forEach((c, i) => {
      if (i > 0) blocks.push({ type: "separator" });
      if (c.message?.role) blocks.push({ type: "label", label: c.message.role });
      if (c.message?.content) addContentBlocks(c.message.content, blocks);
    });
    return blocks;
  }

  // Flattened to_show format: render each key-value pair as label + content
  const entries = Object.entries(data);
  if (entries.length > 0 && entries.every(([k]) => typeof k === "string")) {
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

  // Fallback: render the whole object as JSON
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
      {blocks.map((block, i) => {
        switch (block.type) {
          case "label":
            return <div key={i} className="io-role-label">{block.label}</div>;
          case "markdown":
            return <div key={i}><MarkdownContent markdown={block.content} /></div>;
          case "code":
            return <CodeBlock key={i} code={block.code} language={block.language} />;
          case "separator":
            return <hr key={i} className="io-separator" />;
          default:
            return null;
        }
      })}
    </div>
  );
}

/** Unique key for identifying a specific edit target. */
type EditKey = `${string}:${"Input" | "Output"}`;

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
  onRevert,
}: {
  label: string;
  data: Record<string, unknown>;
  viewMode: ViewMode;
  nodeId?: string;
  editLock: EditKey | null;
  isEdited: boolean;
  hasAnyEdit: boolean;
  onStartEdit: (nodeId: string, label: "Input" | "Output") => void;
  onSaveEdit: (nodeId: string, label: "Input" | "Output", newData: string) => void;
  onSaveAndRerun: (nodeId: string, label: "Input" | "Output", newData: string) => void;
  onCancelEdit: () => void;
  onRevert: (nodeId: string, label: "Input" | "Output") => void;
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

  const handleEditChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const v = e.target.value;
    setEditValue(v);
    generateGhost(v);
  }, [generateGhost]);

  const handleEditKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Tab" && ghost) {
      e.preventDefault();
      const newVal = editValue + ghost;
      setEditValue(newVal);
      setGhost("");
      generateGhost(newVal);
    }
    if (e.key === "Escape" && ghost) {
      setGhost("");
    }
  }, [ghost, editValue, generateGhost]);

  const startEdit = useCallback(() => {
    if (!nodeId || isLocked) return;
    setEditValue(JSON.stringify(data, null, 2));
    setGhost("");
    onStartEdit(nodeId, label as "Input" | "Output");
  }, [data, nodeId, isLocked, onStartEdit, label]);

  const cancelEdit = useCallback(() => {
    setEditValue("");
    onCancelEdit();
  }, [onCancelEdit]);

  const saveEdit = useCallback(() => {
    if (nodeId) {
      onSaveEdit(nodeId, label as "Input" | "Output", editValue);
    }
  }, [nodeId, label, editValue, onSaveEdit]);

  const saveAndRerun = useCallback(() => {
    if (nodeId) {
      onSaveAndRerun(nodeId, label as "Input" | "Output", editValue);
    }
  }, [nodeId, label, editValue, onSaveAndRerun]);

  const handleSuggest = useCallback(() => {
    setSuggesting(true);
    setTimeout(() => {
      try {
        const parsed = JSON.parse(editValue || jsonStr);
        setEditValue(JSON.stringify(parsed, null, 2));
      } catch {
        // keep current value
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
          {isEdited && !isActiveEdit && (
            <button className="io-revert-btn" onClick={() => nodeId && onRevert(nodeId, label as "Input" | "Output")} title="Revert edit">
              <Undo2 size={11} /> Revert
            </button>
          )}
          {!isActiveEdit && (
            <div className={isLocked ? "io-edit-locked-wrapper" : ""} title={isLocked ? "Revert the current edit before editing another field" : `Edit ${label.toLowerCase()}`}>
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

// ── Node header ──────────────────────────────────────────

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

// ── Full trace flow view (all nodes, scrollable) ───────

function FullTraceFlow({
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
  onRevert,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  viewMode: ViewMode;
  focusedNodeId: string | null;
  nodeRefs: React.MutableRefObject<Map<string, HTMLDivElement>>;
  onCardClick: (nodeId: string) => void;
  editLock: EditKey | null;
  editedFields: Set<EditKey>;
  onStartEdit: (nodeId: string, label: "Input" | "Output") => void;
  onSaveEdit: (nodeId: string, label: "Input" | "Output", newData: string) => void;
  onSaveAndRerun: (nodeId: string, label: "Input" | "Output", newData: string) => void;
  onCancelEdit: () => void;
  onRevert: (nodeId: string, label: "Input" | "Output") => void;
}) {
  const sorted = useMemo(() => topoSortNodes(nodes, edges), [nodes, edges]);
  const hasAnyEdit = editedFields.size > 0;

  return (
    <div className="run-detail-io-scroll">
      {sorted.map((node) => {
        const hasEdit = editedFields.has(`${node.id}:Input`) || editedFields.has(`${node.id}:Output`);
        return (
          <div
            key={node.id}
            ref={(el) => { if (el) nodeRefs.current.set(node.id, el); }}
            className={`trace-node-card${node.id === focusedNodeId ? " focused" : ""}${hasEdit ? " trace-node-edited" : ""}`}
            onClick={() => onCardClick(node.id)}
          >
            <NodeHeader node={node} />
            <IOPanel label="Input" data={node.input} viewMode={viewMode} nodeId={node.id} editLock={editLock} isEdited={editedFields.has(`${node.id}:Input`)} hasAnyEdit={hasAnyEdit} onStartEdit={onStartEdit} onSaveEdit={onSaveEdit} onSaveAndRerun={onSaveAndRerun} onCancelEdit={onCancelEdit} onRevert={onRevert} />
            <IOPanel label="Output" data={node.output} viewMode={viewMode} nodeId={node.id} editLock={editLock} isEdited={editedFields.has(`${node.id}:Output`)} hasAnyEdit={hasAnyEdit} onStartEdit={onStartEdit} onSaveEdit={onSaveEdit} onSaveAndRerun={onSaveAndRerun} onCancelEdit={onCancelEdit} onRevert={onRevert} />
          </div>
        );
      })}
    </div>
  );
}

/** Exposes useReactFlow() methods to the parent via ref. */
interface GraphApiHandle {
  setCenter: ReturnType<typeof useReactFlow>["setCenter"];
}

function GraphApi({ apiRef }: { apiRef: React.MutableRefObject<GraphApiHandle | null> }) {
  const { setCenter } = useReactFlow();
  useEffect(() => {
    apiRef.current = { setCenter };
    return () => { apiRef.current = null; };
  }, [setCenter, apiRef]);
  return null;
}

// ── Main RunView ───────────────────────────────────────

export function RunView() {
  const { projectId, sessionId } = useParams();

  // Data state
  const [projectName, setProjectName] = useState("");
  const [runName, setRunName] = useState("");
  const [runResult, setRunResult] = useState<string>("");
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);

  // Fetch project, experiment detail, and graph on mount
  useEffect(() => {
    if (!projectId || !sessionId) return;
    let cancelled = false;

    async function load() {
      try {
        const [proj, detail, graphResp] = await Promise.all([
          fetchProject(projectId!),
          fetchExperimentDetail(sessionId!),
          fetchGraph(sessionId!),
        ]);
        if (cancelled) return;
        setProjectName(proj.name);
        setRunName(detail.run_name);
        setRunResult(detail.result);
        const parsed = parseGraphPayload(graphResp.payload);
        setGraphNodes(parsed.nodes);
        setGraphEdges(parsed.edges);
      } catch (err) {
        console.error("Failed to load run data:", err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [projectId, sessionId]);

  // Subscribe to WebSocket for live graph updates
  useEffect(() => {
    if (!sessionId) return;
    return subscribe("graph_update", (msg) => {
      if (msg.session_id !== sessionId) return;
      const parsed = parseGraphPayload(msg.payload);
      setGraphNodes(parsed.nodes);
      setGraphEdges(parsed.edges);
    });
  }, [sessionId]);

  // UI state
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("pretty");
  const [rerunning, setRerunning] = useState(false);
  const nodeRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const graphApi = useRef<GraphApiHandle | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);

  // Compute full graph layout (positions + routed edges)
  const graphLayout = useMemo(
    () => layoutGraph(graphNodes, graphEdges),
    [graphNodes, graphEdges],
  );
  const sortedNodeIds = graphLayout.sortedIds;

  // Center on the last topological node when nodes are added/removed (not on content-only edits).
  const prevNodeCountRef = useRef(0);
  useEffect(() => {
    if (!sortedNodeIds.length) return;
    if (sortedNodeIds.length === prevNodeCountRef.current) return;
    prevNodeCountRef.current = sortedNodeIds.length;

    const lastId = sortedNodeIds[sortedNodeIds.length - 1];
    const pos = graphLayout.positions.get(lastId);
    if (!pos) return;
    const cx = pos.x + NODE_W / 2;
    const cy = pos.y + NODE_H / 2;

    setFocusedNodeId(lastId);

    let attempts = 0;
    const tryCenter = () => {
      if (attempts++ >= 50) return;
      const api = graphApi.current;
      if (!api) { requestAnimationFrame(tryCenter); return; }
      api.setCenter(cx, cy, { zoom: 1, duration: 0 });
      requestAnimationFrame(() => {
        const el = nodeRefs.current.get(lastId);
        if (el) {
          const scrollParent = el.closest(".run-detail-io-scroll");
          if (scrollParent) {
            const marginTop = parseInt(getComputedStyle(el).marginTop, 10) || 0;
            scrollParent.scrollTo({ top: el.offsetTop - scrollParent.offsetTop - marginTop, behavior: "instant" });
          }
        }
      });
    };
    requestAnimationFrame(tryCenter);
  }, [sortedNodeIds, graphLayout]);

  // Edit state
  const [editLock, setEditLock] = useState<EditKey | null>(null);
  const [editedFields, setEditedFields] = useState<Set<EditKey>>(new Set());

  const handleStartEdit = useCallback((nodeId: string, label: "Input" | "Output") => {
    setEditLock(`${nodeId}:${label}`);
  }, []);

  const handleSaveEdit = useCallback((nodeId: string, label: "Input" | "Output", newData: string) => {
    if (!sessionId) return;
    const key: EditKey = `${nodeId}:${label}`;
    const fn = label === "Input" ? editInput : editOutput;
    fn(sessionId, nodeId, newData).catch(console.error);
    setEditedFields((prev) => new Set(prev).add(key));
    setEditLock(null);
  }, [sessionId]);

  const handleCancelEdit = useCallback(() => {
    setEditLock(null);
  }, []);

  const handleRevert = useCallback((nodeId: string, label: "Input" | "Output") => {
    const key: EditKey = `${nodeId}:${label}`;
    setEditedFields((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
    // TODO: revert on backend (re-fetch graph node)
  }, []);

  const handleSaveAndRerun = useCallback((nodeId: string, label: "Input" | "Output", newData: string) => {
    if (!sessionId) return;
    const key: EditKey = `${nodeId}:${label}`;
    const fn = label === "Input" ? editInput : editOutput;
    fn(sessionId, nodeId, newData)
      .then(() => restartRun(sessionId))
      .catch(console.error);
    setEditedFields((prev) => new Set(prev).add(key));
    setEditLock(null);
    setRerunning(true);
  }, [sessionId]);

  const handleRerun = useCallback(() => {
    if (!sessionId) return;
    setRerunning(true);
    restartRun(sessionId).catch(console.error);
  }, [sessionId]);

  // Result state (pass/fail)
  const handleResultToggle = useCallback((result: "satisfactory" | "failed") => {
    if (!sessionId) return;
    const newResult = runResult === (result === "satisfactory" ? "Satisfactory" : "Failed") ? "" : (result === "satisfactory" ? "Satisfactory" : "Failed");
    setRunResult(newResult);
    updateResult(sessionId, newResult).catch(console.error);
  }, [sessionId, runResult]);

  const handleErase = useCallback(() => {
    if (!sessionId) return;
    setEditedFields(new Set());
    setEditLock(null);
    eraseRun(sessionId).catch(console.error);
    setRerunning(true);
  }, [sessionId]);

  // Reset rerunning state when graph updates (rerun completed)
  useEffect(() => {
    if (rerunning && graphNodes.length > 0) {
      setRerunning(false);
    }
  }, [graphNodes, rerunning]);

  // ReactFlow data from layout engine
  const nodeById = useMemo(() => new Map(graphNodes.map((n) => [n.id, n])), [graphNodes]);

  const rfNodes: Node[] = useMemo(() => {
    return sortedNodeIds.map((id) => {
      const pos = graphLayout.positions.get(id);
      const node = nodeById.get(id);
      if (!pos || !node) return null;
      return {
        id,
        type: "llmNode",
        position: { x: pos.x, y: pos.y },
        data: { label: node.label, model: node.model, nodeId: id, borderColor: node.border_color },
      };
    }).filter(Boolean) as Node[];
  }, [sortedNodeIds, graphLayout, nodeById]);

  const rfEdges: Edge[] = useMemo(() => {
    return graphLayout.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: "routed",
      sourceHandle: e.sourceHandle,
      targetHandle: e.targetHandle,
      data: { points: e.points, highlighted: e.target === focusedNodeId },
    }));
  }, [graphLayout, focusedNodeId]);

  const scrollToNode = useCallback((nodeId: string, behavior: ScrollBehavior = "smooth") => {
    const el = nodeRefs.current.get(nodeId);
    if (!el) return;
    const scrollParent = el.closest(".run-detail-io-scroll");
    if (scrollParent) {
      const marginTop = parseInt(getComputedStyle(el).marginTop, 10) || 0;
      scrollParent.scrollTo({ top: el.offsetTop - scrollParent.offsetTop - marginTop, behavior });
    }
  }, []);

  /** Center graph on a node by index and update focus + detail scroll. */
  const focusNodeByIndex = useCallback((idx: number) => {
    const api = graphApi.current;
    if (!api || !sortedNodeIds.length) return;
    const clamped = Math.max(0, Math.min(sortedNodeIds.length - 1, idx));
    const nodeId = sortedNodeIds[clamped];
    const pos = graphLayout.positions.get(nodeId);
    if (!pos) return;
    api.setCenter(pos.x + NODE_W / 2, pos.y + NODE_H / 2, { zoom: 1, duration: 300 });
    setSelectedNodeId(nodeId);
    setFocusedNodeId(nodeId);
    scrollToNode(nodeId, "smooth");
  }, [sortedNodeIds, graphLayout, scrollToNode]);

  /** Center on a node by id. */
  const centerOnNode = useCallback((nodeId: string) => {
    const idx = sortedNodeIds.indexOf(nodeId);
    if (idx >= 0) focusNodeByIndex(idx);
  }, [sortedNodeIds, focusNodeByIndex]);

  const focusedRef = useRef(focusedNodeId);
  focusedRef.current = focusedNodeId;

  // Scroll-wheel navigates between nodes (throttled: fires immediately, then cooldown)
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    let cooldownUntil = 0;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const now = performance.now();
      if (now < cooldownUntil) return;
      if (Math.abs(e.deltaY) < 4) return; // ignore tiny trackpad noise
      const dir = e.deltaY > 0 ? 1 : -1;
      const curIdx = sortedNodeIds.indexOf(focusedRef.current ?? "");
      focusNodeByIndex(curIdx + dir);
      cooldownUntil = now + 1000;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => { el.removeEventListener("wheel", onWheel); };
  }, [sortedNodeIds, focusNodeByIndex]);

  // Arrow-key navigation between nodes (same cooldown as scroll)
  useEffect(() => {
    let cooldownUntil = 0;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
      // Don't capture when user is typing in an input/textarea
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      e.preventDefault();
      const now = performance.now();
      if (now < cooldownUntil) return;
      const dir = e.key === "ArrowDown" ? 1 : -1;
      const curIdx = sortedNodeIds.indexOf(focusedRef.current ?? "");
      focusNodeByIndex(curIdx + dir);
      cooldownUntil = now + 300;
    };
    window.addEventListener("keydown", onKeyDown);
    return () => { window.removeEventListener("keydown", onKeyDown); };
  }, [sortedNodeIds, focusNodeByIndex]);

  // Re-center on focused node when container resizes
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const api = graphApi.current;
      const id = focusedRef.current;
      if (!api || !id) return;
      const pos = graphLayout.positions.get(id);
      if (!pos) return;
      api.setCenter(pos.x + NODE_W / 2, pos.y + NODE_H / 2, { zoom: 1, duration: 0 });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [graphLayout]);

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    centerOnNode(node.id);
  }, [centerOnNode]);

  const onCardClick = useCallback((nodeId: string) => {
    centerOnNode(nodeId);
  }, [centerOnNode]);

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  const nodesWithSelection = useMemo(
    () => rfNodes.map((n) => ({
      ...n,
      selected: n.id === focusedNodeId,
      data: { ...n.data, focused: n.id === focusedNodeId },
    })),
    [rfNodes, focusedNodeId]
  );

  const hasGraph = graphNodes.length > 0;

  if (loading) {
    return (
      <div className="run-view">
        <div className="empty-state">
          <Loader2 size={24} className="fa-spinner" />
          <div className="empty-state-title" style={{ marginTop: 12 }}>Loading run…</div>
        </div>
      </div>
    );
  }

  return (
    <div className="run-view">
      <Breadcrumb
        items={[
          { label: "Organization", to: "/" },
          { label: projectName || "Project", to: `/project/${projectId}` },
          { label: runName || sessionId || "Run" },
        ]}
      />
      <div className="run-view-columns">
      <div className="run-view-left">

      {/* Top bar */}
      <div className="run-top-bar">
        <div className="run-detail-header-title">Full Trace</div>
        <div className="run-detail-header-actions">
          <div className="view-mode-toggle">
            <button
              className={`view-mode-btn${viewMode === "pretty" ? " active" : ""}`}
              onClick={() => setViewMode("pretty")}
            >
              Pretty
            </button>
            <button
              className={`view-mode-btn${viewMode === "json" ? " active" : ""}`}
              onClick={() => setViewMode("json")}
            >
              JSON
            </button>
          </div>
          <button
            className="run-rerun-btn"
            onClick={handleRerun}
            disabled={rerunning}
            title="Re-run with edits"
          >
            {rerunning ? (
              <><Loader2 size={13} className="fa-spinner" /> Re-running…</>
            ) : (
              <><RotateCcw size={13} /> Re-run</>
            )}
          </button>
          <button
            className="run-rerun-btn run-reset-btn"
            onClick={handleErase}
            title="Reset run to original state"
          >
            <Undo2 size={13} /> Reset All Edits
          </button>
        </div>
      </div>

      <div className="run-view-body">
        {/* Left: Graph */}
        <div className="run-graph-panel">
          <div className="run-graph-canvas" ref={canvasRef}>
            {hasGraph ? (
              <ReactFlowProvider>
                <ReactFlow
                  nodes={nodesWithSelection}
                  edges={rfEdges}
                  nodeTypes={nodeTypes}
                  edgeTypes={edgeTypes}
                  onNodeClick={onNodeClick}
                  onPaneClick={onPaneClick}
                  onSelectionChange={({ nodes }) => { if (!nodes.length) setSelectedNodeId(null); }}
                  proOptions={{ hideAttribution: true }}
                  nodesDraggable={false}
                  panOnDrag={false}
                  zoomOnScroll={false}
                  zoomOnPinch={false}
                  zoomOnDoubleClick={false}
                  preventScrolling
                >
                  <GraphApi apiRef={graphApi} />
                </ReactFlow>
              </ReactFlowProvider>
            ) : (
              <div className="empty-state">
                <div className="empty-state-title">No graph data</div>
              </div>
            )}

            {/* Focus indicator — arrowhead from right edge pointing inward */}
            <div className="graph-focus-arrow" />

            {/* Controls (bottom-right) */}
            <div className="graph-controls-panel">
              <button
                className={`graph-controls-btn${runResult === "Satisfactory" ? " active-pass" : ""}`}
                title={runResult === "Satisfactory" ? "Clear result" : "Mark as Satisfactory"}
                onClick={() => handleResultToggle("satisfactory")}
              >
                <ThumbsUp size={12} color={runResult === "Satisfactory" ? "#fff" : "#4caf50"} />
              </button>
              <button
                className={`graph-controls-btn${runResult === "Failed" ? " active-fail" : ""}`}
                title={runResult === "Failed" ? "Clear result" : "Mark as Failed"}
                onClick={() => handleResultToggle("failed")}
              >
                <ThumbsDown size={12} color={runResult === "Failed" ? "#fff" : "#e05252"} />
              </button>
            </div>
          </div>
        </div>

        {/* Center: I/O Detail */}
        <div className="run-detail-panel">
          <div className="run-detail-body">
            {hasGraph ? (
              <FullTraceFlow
                nodes={graphNodes}
                edges={graphEdges}
                viewMode={viewMode}
                focusedNodeId={focusedNodeId}
                nodeRefs={nodeRefs}
                onCardClick={onCardClick}
                editLock={editLock}
                editedFields={editedFields}
                onStartEdit={handleStartEdit}
                onSaveEdit={handleSaveEdit}
                onSaveAndRerun={handleSaveAndRerun}
                onCancelEdit={handleCancelEdit}
                onRevert={handleRevert}
              />
            ) : (
              <div className="empty-state" style={{ flex: 1 }}>
                <div className="empty-state-title">No graph data</div>
              </div>
            )}
          </div>
        </div>

      </div>
      </div>{/* end run-view-left */}
      </div>{/* end run-view-columns */}
    </div>
  );
}
