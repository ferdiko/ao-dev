import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { useParams } from "react-router-dom";
import {
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  Controls,
  type Node,
  type Edge,
  type NodeTypes,
  type NodeProps,
  Handle,
  Position,
  MarkerType,
  useOnSelectionChange,
  useViewport,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { Breadcrumb } from "../components/Breadcrumb";
import { AttachmentStrip, extractAttachments } from "../components/AttachmentPreview";
import { mockProjects, mockRuns, mockGraphs, mockTags, resolveTagNames } from "../data/mock";
import type { GraphNode, Tag, Span } from "../data/mock";
import { Sparkles, Pencil, RotateCcw, Loader2, Undo2, ThumbsUp, ThumbsDown, Copy } from "lucide-react";
import { TagDropdown } from "../components/TagDropdown";
import { TraceChat } from "../components/TraceChat";

// ── Graph layout helpers ───────────────────────────────

const NODE_W = 170;
const NODE_H = 46; // Approximate rendered height (actual is ~45.4px after CSS padding)
const V_GAP = 50;

/** Collapse nodes into spans at the given abstraction level.
 *  Level 0 = all nodes visible. Level 1 = spans collapsed into single nodes.
 */
function applyAbstraction(
  graphNodes: GraphNode[],
  graphEdges: { source: string; target: string }[],
  spans: Span[] | undefined,
  level: number,
): { nodes: GraphNode[]; edges: { source: string; target: string; id: string }[]; collapsedSpans: Map<string, Span> } {
  const collapsedSpans = new Map<string, Span>();
  if (level === 0 || !spans?.length) {
    return { nodes: graphNodes, edges: graphEdges as any, collapsedSpans };
  }

  // Build set of all node IDs consumed by spans
  const consumedNodeIds = new Set<string>();
  for (const span of spans) {
    for (const nid of span.nodeIds) consumedNodeIds.add(nid);
  }

  // Create synthetic nodes for each span
  const syntheticNodes: GraphNode[] = [];
  const nodeToSpan = new Map<string, string>(); // original node id → span id
  for (const span of spans) {
    for (const nid of span.nodeIds) nodeToSpan.set(nid, span.id);
    collapsedSpans.set(span.id, span);
    // Create a synthetic GraphNode for the span
    const childNodes = span.nodeIds.map((nid) => graphNodes.find((n) => n.id === nid)).filter(Boolean) as GraphNode[];
    const totalLatency = childNodes.reduce((sum, n) => sum + n.latency, 0);
    syntheticNodes.push({
      id: span.id,
      label: span.label,
      description: `${childNodes.length} nodes`,
      nodeType: "llm",
      input: childNodes[0]?.input ?? {},
      output: childNodes[childNodes.length - 1]?.output ?? {},
      latency: totalLatency,
      model: childNodes.map((n) => n.model || n.toolName || "").filter(Boolean).join(", "),
    });
  }

  // Keep nodes not in any span
  const remainingNodes = graphNodes.filter((n) => !consumedNodeIds.has(n.id));
  const allNodes = [...syntheticNodes, ...remainingNodes];

  // Remap edges: replace node ids with span ids, deduplicate, remove self-loops
  const edgeSet = new Set<string>();
  const remappedEdges: { source: string; target: string; id: string }[] = [];
  for (const e of graphEdges) {
    const src = nodeToSpan.get(e.source) ?? e.source;
    const tgt = nodeToSpan.get(e.target) ?? e.target;
    if (src === tgt) continue; // self-loop within span
    const key = `${src}->${tgt}`;
    if (edgeSet.has(key)) continue;
    edgeSet.add(key);
    remappedEdges.push({ id: `e-${src}-${tgt}`, source: src, target: tgt });
  }

  return { nodes: allNodes, edges: remappedEdges, collapsedSpans };
}

/** Vertical-only layout: topological sort → stack nodes in a single column. */
function layoutNodes(
  graphNodes: GraphNode[],
  graphEdges: { source: string; target: string }[],
  collapsedSpans?: Map<string, Span>,
): Node[] {
  const sorted = topoSortNodes(graphNodes, graphEdges);
  return sorted.map((n, i) => {
    const isSpan = collapsedSpans?.has(n.id);
    return {
      id: n.id,
      type: isSpan ? "spanNode" : "llmNode",
      position: { x: 0, y: i * (NODE_H + V_GAP) },
      data: { label: n.label, description: n.description, model: n.model, toolName: n.toolName, nodeType: n.nodeType, nodeId: n.id },
    };
  });
}

/** Topological sort of nodes for the full-trace flow view. */
function topoSortNodes(graphNodes: GraphNode[], graphEdges: { source: string; target: string }[]): GraphNode[] {
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
  const d = data as { label: string; description?: string; model?: string; toolName?: string; nodeType: string; nodeId: string; focused?: boolean };
  const typeLabel = d.nodeType === "tool" ? `MCP · ${d.toolName ?? "Tool"}` : d.model;
  return (
    <div className={`graph-llm-node${selected ? " selected" : ""}${d.focused ? " focused" : ""}`}>

      <Handle type="target" position={Position.Top} className="graph-handle" />
      <div className="graph-node-label">{d.label}</div>
      {typeLabel && <div className="graph-node-model">{typeLabel}</div>}
      <Handle type="source" position={Position.Bottom} className="graph-handle" />
    </div>
  );
}

function SpanNode({ data, selected }: NodeProps) {
  const d = data as { label: string; description?: string; model?: string; nodeId: string; focused?: boolean };
  return (
    <div className={`graph-span-node${selected ? " selected" : ""}${d.focused ? " focused" : ""}`}>

      <Handle type="target" position={Position.Top} className="graph-handle" />
      <div className="graph-node-label">{d.label}</div>
      {d.description && <div className="graph-node-model">{d.description}</div>}
      <Handle type="source" position={Position.Bottom} className="graph-handle" />
    </div>
  );
}

const nodeTypes: NodeTypes = { llmNode: LLMNode, spanNode: SpanNode };

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

/** Extract structured content from LLM I/O data for pretty rendering. */
function extractPrettyBlocks(data: Record<string, unknown>): Array<{ type: "role"; role: string } | { type: "markdown"; content: string } | { type: "code"; code: string; language: string } | { type: "separator" }> {
  const blocks: Array<{ type: "role"; role: string } | { type: "markdown"; content: string } | { type: "code"; code: string; language: string } | { type: "separator" }> = [];

  function addContentBlocks(content: string) {
    // Split on markdown fenced code blocks, preserving language tag
    const parts = content.split(/(```\w*\n[\s\S]*?```)/g);
    for (const part of parts) {
      const fenceMatch = part.match(/^```(\w*)\n([\s\S]*?)```$/);
      if (fenceMatch) {
        const lang = fenceMatch[1] || detectLanguage(fenceMatch[2]) || "text";
        blocks.push({ type: "code", code: fenceMatch[2].replace(/\n$/, ""), language: lang });
      } else if (part.trim()) {
        // Auto-detect code in unfenced text
        const detected = detectLanguage(part.trim());
        if (detected) {
          blocks.push({ type: "code", code: part.trim(), language: detected });
        } else {
          blocks.push({ type: "markdown", content: part });
        }
      }
    }
  }

  // Chat messages format (input)
  const messages = data.messages as Array<{ role: string; content: string | Array<{ type: string; text?: string }> }> | undefined;
  if (messages) {
    messages.forEach((m, i) => {
      if (i > 0) blocks.push({ type: "separator" });
      blocks.push({ type: "role", role: m.role });
      if (typeof m.content === "string") {
        addContentBlocks(m.content);
      } else if (Array.isArray(m.content)) {
        for (const part of m.content) {
          if (part.type === "text" && part.text) addContentBlocks(part.text);
          // image_url parts are handled by extractAttachments, skip here
        }
      }
    });
    return blocks;
  }

  // Chat choices format (output)
  const choices = data.choices as Array<{ message: { role: string; content: string } }> | undefined;
  if (choices) {
    choices.forEach((c, i) => {
      if (i > 0) blocks.push({ type: "separator" });
      if (c.message?.role) blocks.push({ type: "role", role: c.message.role });
      if (c.message?.content) addContentBlocks(c.message.content);
    });
    return blocks;
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
          case "role":
            return <div key={i} className="io-role-label">{block.role}</div>;
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
  /** null = no edit active; otherwise the EditKey that's currently being edited */
  editLock: EditKey | null;
  /** Whether this particular panel has a saved edit */
  isEdited: boolean;
  /** Whether any edit exists anywhere (blocks editing other fields) */
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
  // Locked if: actively editing another field, OR a saved edit exists on a different field
  const isLocked = (editLock !== null && !isActiveEdit) || (hasAnyEdit && !isEdited);

  // Simulated copilot suggestions based on JSON context
  const generateGhost = useCallback((value: string) => {
    if (ghostTimer.current) clearTimeout(ghostTimer.current);
    setGhost("");
    if (!value.trim()) return;
    // After a short pause, show a contextual completion
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
        // Mid-key typing — suggest common key completions
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

function TokenBadge({ usage }: { usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number } }) {
  return (
    <div className="token-badge-row">
      <span className="token-badge"><span className="token-label">Prompt</span> {usage.prompt_tokens}</span>
      <span className="token-badge"><span className="token-label">Completion</span> {usage.completion_tokens}</span>
      <span className="token-badge total"><span className="token-label">Total</span> {usage.total_tokens}</span>
    </div>
  );
}

// ── Node header (shared between single-node and full-trace views) ──

function NodeHeader({ node }: { node: GraphNode }) {
  const typeLabel = node.nodeType === "tool"
    ? `MCP · ${node.toolName ?? "Tool"}`
    : node.model ?? "LLM";
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
        <span className="node-card-desc">{node.description}</span>
      </div>
      <div className="node-card-meta-row">
        <span className={`node-card-type ${node.nodeType}`}>{typeLabel}</span>
        <span className="node-card-latency">{node.latency < 1000 ? `${node.latency}ms` : `${(node.latency / 1000).toFixed(1)}s`}</span>
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
  selectedNodeId,
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
  collapsedSpans,
}: {
  nodes: GraphNode[];
  edges: { source: string; target: string }[];
  viewMode: ViewMode;
  selectedNodeId: string | null;
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
  collapsedSpans: Map<string, Span>;
}) {
  const sorted = useMemo(() => topoSortNodes(nodes, edges), [nodes, edges]);
  const hasAnyEdit = editedFields.size > 0;

  return (
    <div className="run-detail-io-scroll">
      {sorted.map((node) => {
        const span = collapsedSpans.get(node.id);
        if (span) {
          // Collapsed span: render as a single summary card
          return (
            <div
              key={node.id}
              ref={(el) => { if (el) nodeRefs.current.set(node.id, el); }}
              className={`trace-node-card trace-span-card${node.id === focusedNodeId ? " focused" : ""}`}
              onClick={() => onCardClick(node.id)}
            >
              <div className="span-card-header">
                <span className="span-card-label">{span.label}</span>
                <span className="span-card-count">{span.nodeIds.length} {span.nodeIds.length === 1 ? "node" : "nodes"}</span>
              </div>
              <IOPanel label="Input" data={node.input} viewMode={viewMode} nodeId={node.id} editLock={editLock} isEdited={false} hasAnyEdit={hasAnyEdit} onStartEdit={onStartEdit} onSaveEdit={onSaveEdit} onSaveAndRerun={onSaveAndRerun} onCancelEdit={onCancelEdit} onRevert={onRevert} />
              <IOPanel label="Output" data={node.output} viewMode={viewMode} nodeId={node.id} editLock={editLock} isEdited={false} hasAnyEdit={hasAnyEdit} onStartEdit={onStartEdit} onSaveEdit={onSaveEdit} onSaveAndRerun={onSaveAndRerun} onCancelEdit={onCancelEdit} onRevert={onRevert} />
            </div>
          );
        }

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

// ── Selection change hook (needs to be inside ReactFlow) ──

function SelectionWatcher({ onSelectionChange }: { onSelectionChange: (ids: string[]) => void }) {
  useOnSelectionChange({
    onChange: ({ nodes }) => onSelectionChange(nodes.map((n) => n.id)),
  });
  return null;
}

/** Helper: find the nearest node to a given Y in flow coordinates. */
function findNearestNode(nodes: Node[], focusY: number): { id: string; x: number; y: number } | null {
  let best: { id: string; x: number; y: number } | null = null;
  let bestDist = Infinity;
  for (const n of nodes) {
    const ncx = n.position.x + (n.measured?.width ?? NODE_W) / 2;
    const ncy = n.position.y + (n.measured?.height ?? NODE_H) / 2;
    const d = Math.abs(ncy - focusY);
    if (d < bestDist) { bestDist = d; best = { id: n.id, x: ncx, y: ncy }; }
  }
  return best;
}

/** Exposes the ReactFlow instance so parent can center on nodes, and syncs viewport scroll to detail panel.
 *  Implements snap-to-node: when panning stops, the graph smoothly snaps to center the nearest node.
 */
function GraphFlowBridge({
  setBridge,
  onViewportTopNode,
  canvasHeight,
  onTranslateExtent,
}: {
  setBridge: (api: { centerOnNode: (id: string) => void }) => void;
  onViewportTopNode: (nodeId: string) => void;
  canvasHeight: number;
  onTranslateExtent: (extent: [[number, number], [number, number]]) => void;
}) {
  const { setCenter, getNodes, getViewport } = useReactFlow();
  const viewport = useViewport();
  const snapTimer = useRef<ReturnType<typeof setTimeout>>();
  // When true, all viewport-change logic is suppressed (we're animating).
  // Starts true to suppress the initial onInit centering animation.
  const animating = useRef(true);
  useState(() => { setTimeout(() => { animating.current = false; }, 800); });

  // Focus line at canvas center — matches ReactFlow's setCenter which targets 50%
  const focusLineOffset = canvasHeight / 2;
  const currentFocused = useRef<string | null>(null);

  /** Compute the focus Y in flow coordinates from a viewport state. */
  const getFocusY = useCallback((vp: { y: number; zoom: number }) =>
    (-vp.y + focusLineOffset) / vp.zoom,
  [focusLineOffset]);

  /** Snap to nearest node if not already centered. Self-verifies after animation. */
  const doSnap = useCallback((duration: number = 200) => {
    if (animating.current) return;
    const nodes = getNodes();
    if (!nodes.length) return;
    const vp = getViewport();
    const fy = getFocusY(vp);
    const best = findNearestNode(nodes, fy);
    if (!best) return;

    // Already centered (within 2px in flow coords) — no snap needed
    if (Math.abs(best.y - fy) < 2) return;

    animating.current = true;
    setCenter(best.x, best.y, { zoom: 1, duration });
    if (best.id !== currentFocused.current) {
      currentFocused.current = best.id;
      onViewportTopNode(best.id);
    }
    // After animation completes, unlock and verify we're actually centered.
    // If viewport drifted (e.g. residual inertia, rounding), snap again.
    setTimeout(() => {
      animating.current = false;
      clearTimeout(snapTimer.current);
      snapTimer.current = setTimeout(() => doSnap(150), 60);
    }, duration + 80);
  }, [getNodes, getViewport, getFocusY, setCenter, onViewportTopNode]);

  const centerOnNode = useCallback(
    (nodeId: string) => {
      animating.current = true;
      clearTimeout(snapTimer.current);
      const node = getNodes().find((n) => n.id === nodeId);
      if (!node) return;
      const x = node.position.x + (node.measured?.width ?? NODE_W) / 2;
      const y = node.position.y + (node.measured?.height ?? NODE_H) / 2;
      setCenter(x, y, { zoom: 1, duration: 600 });
      setTimeout(() => { animating.current = false; }, 700);
    },
    [setCenter, getNodes],
  );

  // Register the bridge on mount
  useState(() => setBridge({ centerOnNode }));

  // Compute scroll extent to prevent panning past first/last node.
  useEffect(() => {
    const nodes = getNodes();
    if (!nodes.length) return;
    let minCY = Infinity, maxCY = -Infinity;
    for (const n of nodes) {
      const cy = n.position.y + (n.measured?.height ?? NODE_H) / 2;
      if (cy < minCY) minCY = cy;
      if (cy > maxCY) maxCY = cy;
    }
    const pad = focusLineOffset;
    onTranslateExtent([[-Infinity, minCY - pad], [Infinity, maxCY + pad]]);
  }, [getNodes, onTranslateExtent, focusLineOffset]);

  // Track user panning and snap after it settles
  const prevY = useRef(viewport.y);

  useEffect(() => {
    if (animating.current) {
      prevY.current = viewport.y;
      return;
    }

    const nodes = getNodes();
    if (!nodes.length) return;

    const userPanned = viewport.y !== prevY.current;
    prevY.current = viewport.y;
    if (!userPanned) return;

    // Immediately update focus to nearest node (no debounce)
    const fy = getFocusY(viewport);
    const nearest = findNearestNode(nodes, fy);
    if (nearest && nearest.id !== currentFocused.current) {
      currentFocused.current = nearest.id;
      onViewportTopNode(nearest.id);
    }

    // Debounced snap: wait for scrolling to fully settle before snapping.
    // 150ms is long enough for trackpad inertia to settle between scroll
    // gestures, ensuring we only snap after the user has stopped scrolling.
    clearTimeout(snapTimer.current);
    snapTimer.current = setTimeout(doSnap, 150);
  }, [viewport.y, viewport.zoom, focusLineOffset, getNodes, getFocusY, onViewportTopNode, doSnap]);

  return null;
}

// ── Main RunView ───────────────────────────────────────

export function RunView() {
  const { projectId, sessionId } = useParams();
  const project = mockProjects.find((p) => p.id === projectId);
  const run = mockRuns.find((r) => r.sessionId === sessionId);
  const graphData = sessionId ? mockGraphs[sessionId] : undefined;

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  // Default focus: last node in topological order (most relevant)
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(() => {
    if (!graphData?.nodes.length) return null;
    const sorted = topoSortNodes(graphData.nodes, graphData.edges);
    return sorted[sorted.length - 1]?.id ?? null;
  });
  const [viewMode, setViewMode] = useState<ViewMode>("pretty");
  const [rerunning, setRerunning] = useState(false);
  const nodeRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const graphBridge = useRef<{ centerOnNode: (id: string) => void } | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [canvasHeight, setCanvasHeight] = useState(600);
  const [translateExtent, setTranslateExtent] = useState<[[number, number], [number, number]]>([[-Infinity, -Infinity], [Infinity, Infinity]]);

  // Track canvas height for focus line positioning
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setCanvasHeight(entry.contentRect.height));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Tag state
  const [allTags, setAllTags] = useState<Tag[]>([...mockTags]);
  const [runTags, setRunTags] = useState<Tag[]>(() =>
    run ? resolveTagNames(run.tags) : [],
  );

  const handleTagToggle = useCallback((tag: Tag) => {
    setRunTags((prev) =>
      prev.some((t) => t.id === tag.id)
        ? prev.filter((t) => t.id !== tag.id)
        : [...prev, tag],
    );
  }, []);

  const handleTagDelete = useCallback((tag: Tag) => {
    setAllTags((prev) => prev.filter((t) => t.id !== tag.id));
    setRunTags((prev) => prev.filter((t) => t.id !== tag.id));
  }, []);

  const handleTagCreate = useCallback(
    (name: string, color: string) => {
      const newTag: Tag = { id: `tag-${Date.now()}`, name, color };
      setAllTags((prev) => [...prev, newTag]);
      setRunTags((prev) => [...prev, newTag]);
    },
    [],
  );

  // Edit state: only one field can be edited at a time
  const [editLock, setEditLock] = useState<EditKey | null>(null);
  const [editedFields, setEditedFields] = useState<Set<EditKey>>(new Set());

  const handleStartEdit = useCallback((nodeId: string, label: "Input" | "Output") => {
    setEditLock(`${nodeId}:${label}`);
  }, []);

  const handleSaveEdit = useCallback((nodeId: string, label: "Input" | "Output", newData: string) => {
    const key: EditKey = `${nodeId}:${label}`;
    // In real app, this would send edit_input/edit_output to the server
    console.log(`Edit ${label} for node ${nodeId}:`, newData);
    setEditedFields((prev) => new Set(prev).add(key));
    setEditLock(null);
  }, []);

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
  }, []);

  const handleSaveAndRerun = useCallback((nodeId: string, label: "Input" | "Output", newData: string) => {
    const key: EditKey = `${nodeId}:${label}`;
    console.log(`Save & Rerun – ${label} for node ${nodeId}:`, newData);
    setEditedFields((prev) => new Set(prev).add(key));
    setEditLock(null);
    // Trigger rerun immediately after saving
    setRerunning(true);
    setTimeout(() => setRerunning(false), 2000);
  }, []);

  const handleRerun = useCallback(() => {
    setRerunning(true);
    setTimeout(() => setRerunning(false), 2000);
  }, []);

  // Result state (pass/fail)
  const [runResult, setRunResult] = useState<"satisfactory" | "failed" | null>(
    run?.success === true ? "satisfactory" : run?.success === false ? "failed" : null,
  );

  const handleResultToggle = useCallback((result: "satisfactory" | "failed") => {
    setRunResult((prev) => (prev === result ? null : result));
  }, []);

  const handleErase = useCallback(() => {
    setEditedFields(new Set());
    setEditLock(null);
  }, []);

  // Abstraction level: 0 = full detail, 1+ = collapsed spans
  const maxAbstractionLevel = graphData?.spans?.length ? 1 : 0;
  const [abstractionLevel, setAbstractionLevel] = useState(0);

  const handleZoomIn = useCallback(() => {
    setAbstractionLevel((l) => Math.max(0, l - 1));
  }, []);

  const handleZoomOut = useCallback(() => {
    setAbstractionLevel((l) => Math.min(maxAbstractionLevel, l + 1));
  }, [maxAbstractionLevel]);

  // Apply abstraction to graph data
  const { abstractedNodes, abstractedEdges, collapsedSpans } = useMemo(() => {
    if (!graphData) return { abstractedNodes: [], abstractedEdges: [], collapsedSpans: new Map<string, Span>() };
    const { nodes, edges, collapsedSpans } = applyAbstraction(
      graphData.nodes, graphData.edges, graphData.spans, abstractionLevel,
    );
    return { abstractedNodes: nodes, abstractedEdges: edges, collapsedSpans };
  }, [graphData, abstractionLevel]);

  const rfNodes = useMemo(() => {
    return layoutNodes(abstractedNodes, abstractedEdges, collapsedSpans);
  }, [abstractedNodes, abstractedEdges, collapsedSpans]);

  const rfEdges: Edge[] = useMemo(() => {
    return abstractedEdges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: "smoothstep",
      animated: false,
      style: { stroke: "var(--color-text-muted)", strokeWidth: 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "var(--color-text-muted)" },
    }));
  }, [abstractedEdges]);

  const scrollToNode = useCallback((nodeId: string, behavior: ScrollBehavior = "smooth") => {
    const el = nodeRefs.current.get(nodeId);
    if (!el) return;
    const scrollParent = el.closest(".run-detail-io-scroll");
    if (scrollParent) {
      const marginTop = parseInt(getComputedStyle(el).marginTop, 10) || 0;
      scrollParent.scrollTo({ top: el.offsetTop - scrollParent.offsetTop - marginTop, behavior });
    }
  }, []);

  // Synced scroll: when graph viewport moves, scroll detail panel to match
  const isUserScrolling = useRef(false);
  const scrollTimeout = useRef<ReturnType<typeof setTimeout>>();

  const onViewportTopNode = useCallback((nodeId: string) => {
    setFocusedNodeId(nodeId);
    setSelectedNodeId(nodeId);
    if (isUserScrolling.current) return;
    scrollToNode(nodeId, "smooth");
  }, [scrollToNode]);

  // Graph node clicked → select + snap graph + scroll right panel
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
    setFocusedNodeId(node.id);
    // Suppress viewport-sync scroll briefly so clicking doesn't fight with sync
    isUserScrolling.current = true;
    clearTimeout(scrollTimeout.current);
    scrollTimeout.current = setTimeout(() => { isUserScrolling.current = false; }, 600);
    graphBridge.current?.centerOnNode(node.id);
    requestAnimationFrame(() => scrollToNode(node.id));
  }, [scrollToNode]);

  // Right-panel card clicked → select + center graph on that node
  const onCardClick = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
    setFocusedNodeId(nodeId);
    isUserScrolling.current = true;
    clearTimeout(scrollTimeout.current);
    scrollTimeout.current = setTimeout(() => { isUserScrolling.current = false; }, 600);
    graphBridge.current?.centerOnNode(nodeId);
    requestAnimationFrame(() => scrollToNode(nodeId));
  }, [scrollToNode]);

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  const onSelectionChange = useCallback((ids: string[]) => {
    if (ids.length === 0) setSelectedNodeId(null);
  }, []);

  const nodesWithSelection = useMemo(
    () => rfNodes.map((n) => ({
      ...n,
      selected: n.id === focusedNodeId,
      data: { ...n.data, focused: n.id === focusedNodeId },
    })),
    [rfNodes, focusedNodeId]
  );

  if (!project || !run) {
    return (
      <div className="run-view">
        <div className="empty-state">
          <div className="empty-state-title">Run not found</div>
        </div>
      </div>
    );
  }

  return (
    <div className="run-view">
      <Breadcrumb
        items={[
          { label: "Organization", to: "/" },
          { label: project.name, to: `/project/${project.id}` },
          { label: run.name },
        ]}
      />
      <div className="run-view-columns">
      <div className="run-view-left">

      {/* Top bar for trace panel */}
      <div className="run-top-bar">
        <div className="run-detail-header-title">Full Trace</div>
        <TagDropdown
          selectedTags={runTags}
          allTags={allTags}
          onToggle={handleTagToggle}
          onCreate={handleTagCreate}
          onDelete={handleTagDelete}
        />
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
            {graphData ? (
              <ReactFlowProvider>
                <ReactFlow
                  nodes={nodesWithSelection}
                  edges={rfEdges}
                  nodeTypes={nodeTypes}
                  onNodeClick={onNodeClick}
                  onPaneClick={onPaneClick}
                  onInit={(instance) => {
                    // Delay centering to allow ReactFlow to measure node dimensions.
                    // Without this, measured.height is undefined and we fall back to
                    // NODE_H which is smaller than the actual rendered height.
                    requestAnimationFrame(() => {
                      const nodes = instance.getNodes();
                      if (nodes.length) {
                        const last = nodes[nodes.length - 1];
                        const x = last.position.x + (last.measured?.width ?? NODE_W) / 2;
                        const y = last.position.y + (last.measured?.height ?? NODE_H) / 2;
                        instance.setCenter(x, y, { zoom: 1 });
                      } else {
                        instance.fitView({ padding: 0.3, maxZoom: 1.1 });
                      }
                    });
                  }}
                  proOptions={{ hideAttribution: true }}
                  minZoom={0.3}
                  maxZoom={2}
                  zoomOnScroll={false}
                  panOnScroll
                  panOnScrollMode={"vertical" as any}
                  panOnScrollSpeed={1}
                  preventScrolling={false}
                  translateExtent={translateExtent}
                >
                  <SelectionWatcher onSelectionChange={onSelectionChange} />
                  <GraphFlowBridge setBridge={(api) => { graphBridge.current = api; }} onViewportTopNode={onViewportTopNode} canvasHeight={canvasHeight} onTranslateExtent={setTranslateExtent} />
                </ReactFlow>
              </ReactFlowProvider>
            ) : (
              <div className="empty-state">
                <div className="empty-state-title">No graph data</div>
              </div>
            )}

            {/* Focus brackets — static viewfinder marks at vertical center, both sides */}
            <div className="graph-focus-bracket bracket-left bracket-top" />
            <div className="graph-focus-bracket bracket-left bracket-bottom" />
            <div className="graph-focus-bracket bracket-right bracket-top" />
            <div className="graph-focus-bracket bracket-right bracket-bottom" />

            {/* Abstraction controls (bottom-left, vertical, small) */}
            <div className="graph-abstraction-controls">
              <button
                className="graph-abstraction-btn"
                title="Zoom in (more detail)"
                onClick={handleZoomIn}
                disabled={abstractionLevel === 0}
              >
                <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor"><path d="M4.5 0v10h1V0zM0 4.5h10v1H0z"/></svg>
              </button>
              <button
                className="graph-abstraction-btn"
                title="Zoom out (more abstract)"
                onClick={handleZoomOut}
                disabled={abstractionLevel >= maxAbstractionLevel}
              >
                <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor"><path d="M0 4.5h10v1H0z"/></svg>
              </button>
            </div>

            {/* Unified controls (bottom-right) */}
            <div className="graph-controls-panel">
              <button className="graph-controls-btn" title="Pause">
                <svg width="12" height="12" viewBox="0 0 16 16" fill="#d4a825"><path d="M5.5 2.75V13.25C5.5 13.664 5.164 14 4.75 14C4.336 14 4 13.664 4 13.25V2.75C4 2.336 4.336 2 4.75 2C5.164 2 5.5 2.336 5.5 2.75ZM11.25 2C10.836 2 10.5 2.336 10.5 2.75V13.25C10.5 13.664 10.836 14 11.25 14C11.664 14 12 13.664 12 13.25V2.75C12 2.336 11.664 2 11.25 2Z"/></svg>
              </button>
              <button className="graph-controls-btn" title="Continue">
                <svg width="12" height="12" viewBox="0 0 16 16" fill="#7fc17b"><path d="M14.578 7.149L7.578 2.186C7.397 2.058 7.198 2 7.003 2C6.484 2 6 2.411 6 3.002V13.003C6 13.594 6.485 14.005 7.004 14.005C7.201 14.005 7.403 13.946 7.585 13.815L14.585 8.777C15.142 8.376 15.139 7.546 14.579 7.15L14.578 7.149ZM7.5 12.027V3.969L13.14 7.968L7.5 12.027ZM3.5 2.75V13.25C3.5 13.664 3.164 14 2.75 14C2.336 14 2 13.664 2 13.25V2.75C2 2.336 2.336 2 2.75 2C3.164 2 3.5 2.336 3.5 2.75Z"/></svg>
              </button>
              <button className="graph-controls-btn" title="Abort">
                <svg width="12" height="12" viewBox="0 0 16 16" fill="#e05252"><path d="M12.5 3.5V12.5H3.5V3.5H12.5ZM12.5 2H3.5C2.672 2 2 2.672 2 3.5V12.5C2 13.328 2.672 14 3.5 14H12.5C13.328 14 14 13.328 14 12.5V3.5C14 2.672 13.328 2 12.5 2Z"/></svg>
              </button>
              <div className="graph-controls-spacer" />
              <button
                className={`graph-controls-btn${runResult === "satisfactory" ? " active-pass" : ""}`}
                title={runResult === "satisfactory" ? "Clear result" : "Mark as Satisfactory"}
                onClick={() => handleResultToggle("satisfactory")}
              >
                <ThumbsUp size={12} color={runResult === "satisfactory" ? "#fff" : "#4caf50"} />
              </button>
              <button
                className={`graph-controls-btn${runResult === "failed" ? " active-fail" : ""}`}
                title={runResult === "failed" ? "Clear result" : "Mark as Failed"}
                onClick={() => handleResultToggle("failed")}
              >
                <ThumbsDown size={12} color={runResult === "failed" ? "#fff" : "#e05252"} />
              </button>
            </div>
          </div>
        </div>

        {/* Center: I/O Detail */}
        <div className="run-detail-panel">
          <div className="run-detail-body">
            {graphData ? (
              <FullTraceFlow
                nodes={abstractedNodes}
                edges={abstractedEdges}
                viewMode={viewMode}
                selectedNodeId={selectedNodeId}
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
                collapsedSpans={collapsedSpans}
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

      {/* Right: Chat (full height) */}
      <div className="run-chat-panel">
        <TraceChat />
      </div>
      </div>{/* end run-view-columns */}
    </div>
  );
}
