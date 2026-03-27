import { useState, useCallback, useRef, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ChevronRight,
  Folder,
  FileText,
  Plus,
  FolderPlus,
  Trash2,
  Pencil,
  Sparkles,
  Loader2,
  X,
  Eye,
  PenLine,
  Check,
} from "lucide-react";
import { createMockFilesystem, type FSNode } from "../data/priors-mock";
import { mockProjects } from "../data/mock";
import { Breadcrumb } from "../components/Breadcrumb";

// ============================================================
// Types & Helpers
// ============================================================

function getChildren(nodes: FSNode[], parentId: string): FSNode[] {
  return nodes
    .filter((n) => n.parentId === parentId)
    .sort((a, b) => {
      if (a.type !== b.type) return a.type === "folder" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
}

function getAllDescendantIds(nodes: FSNode[], folderId: string): string[] {
  const ids: string[] = [];
  const stack = [folderId];
  while (stack.length) {
    const id = stack.pop()!;
    for (const child of nodes.filter((n) => n.parentId === id)) {
      ids.push(child.id);
      if (child.type === "folder") stack.push(child.id);
    }
  }
  return ids;
}

let _idCounter = 100;
function genId() {
  return `fs-${_idCounter++}`;
}

// ============================================================
// Taxonomy Diff Types
// ============================================================

/** A single entry in the diff tree. */
interface DiffEntry {
  name: string;
  type: "folder" | "file";
  status: "unchanged" | "added" | "deleted" | "modified";
  depth: number;
  /** For folders: whether children are shown */
  expanded?: boolean;
}

/** Mock content for files in the diff (new/modified files). */
const DIFF_FILE_CONTENT: Record<string, { original?: string; proposed: string }> = {
  "query-plan-analysis.md": {
    proposed: `# Query Plan Analysis

## Reading EXPLAIN Output

Use \`EXPLAIN ANALYZE\` to see actual vs estimated rows.

## Common Bottlenecks

- Sequential scans on large tables
- Nested loop joins with no index
- Sort operations spilling to disk

## Tips

Always check for index usage on WHERE and JOIN columns.
`,
  },
  "denormalization-patterns.md": {
    proposed: `# Denormalization Patterns

## When to Denormalize

- Read-heavy workloads with complex joins
- Caching computed aggregates
- Materialized views for dashboards

## Common Patterns

- Pre-computed columns (e.g. \`order_total\`)
- Duplicating foreign key data for read speed
- JSON columns for flexible attributes
`,
  },
  "code-review-checklist.md": {
    proposed: `# Code Review Checklist

## SQL Reviews

- [ ] All queries use parameterized inputs
- [ ] Indexes exist for frequently filtered columns
- [ ] No SELECT * in production code
- [ ] Migrations are reversible

## General

- [ ] Error handling covers edge cases
- [ ] Logging is sufficient for debugging
`,
  },
  "normalization-rules.md": {
    original: `# Normalization Rules

## First Normal Form (1NF)

Each column contains atomic values. No repeating groups.

## Second Normal Form (2NF)

All non-key columns depend on the entire primary key.

## Third Normal Form (3NF)

No transitive dependencies between non-key columns.
`,
    proposed: `# Normalization Rules

## First Normal Form (1NF)

Each column contains atomic values. No repeating groups.

## Second Normal Form (2NF)

All non-key columns depend on the entire primary key.

## Third Normal Form (3NF)

No transitive dependencies between non-key columns.

## When to Break Normalization

Sometimes denormalization improves read performance. See denormalization-patterns.md for common patterns and trade-offs.
`,
  },
  "query-optimization.md": {
    original: `# Query Optimization

## Index Usage

Ensure WHERE and JOIN columns are indexed.

## Avoid SELECT *

Select only needed columns to reduce I/O.

## Use EXPLAIN

Always verify query plans before deploying.
`,
    proposed: `# Query Optimization

## Index Selection

Ensure WHERE, JOIN, and ORDER BY columns are indexed. Prefer composite indexes for multi-column filters.

## Avoid SELECT *

Select only needed columns to reduce I/O and network transfer.

## Query Plans

Always run EXPLAIN ANALYZE before deploying. Look for sequential scans and sort spills.

## Connection Pooling

Use PgBouncer or similar to manage connection overhead.
`,
  },
};

/** Mock diff: simulates AI proposing reorganization of the current taxonomy. */
function generateMockDiff(): DiffEntry[] {
  return [
    // Root stays
    { name: "priors", type: "folder", status: "unchanged", depth: 0, expanded: true },

    // "Error Handling" renamed to "Error Handling & Debugging" (delete old, add new)
    { name: "Error Handling", type: "folder", status: "deleted", depth: 1, expanded: true },
    { name: "common-sql-errors.md", type: "file", status: "deleted", depth: 2 },
    { name: "debugging-tips.md", type: "file", status: "deleted", depth: 2 },

    { name: "Error Handling & Debugging", type: "folder", status: "added", depth: 1, expanded: true },
    { name: "common-sql-errors.md", type: "file", status: "unchanged", depth: 2 },
    { name: "debugging-tips.md", type: "file", status: "unchanged", depth: 2 },
    { name: "query-plan-analysis.md", type: "file", status: "added", depth: 2 },

    // Schema Design unchanged
    { name: "Schema Design", type: "folder", status: "unchanged", depth: 1, expanded: true },
    { name: "normalization-rules.md", type: "file", status: "modified", depth: 2 },
    { name: "denormalization-patterns.md", type: "file", status: "added", depth: 2 },

    // "SQL Best Practices" renamed to "Query Optimization"
    { name: "SQL Best Practices", type: "folder", status: "deleted", depth: 1, expanded: true },
    { name: "indexing-strategies.md", type: "file", status: "deleted", depth: 2 },
    { name: "join-patterns.md", type: "file", status: "deleted", depth: 2 },
    { name: "query-optimization.md", type: "file", status: "deleted", depth: 2 },

    { name: "Query Optimization", type: "folder", status: "added", depth: 1, expanded: true },
    { name: "query-optimization.md", type: "file", status: "modified", depth: 2 },
    { name: "indexing-strategies.md", type: "file", status: "unchanged", depth: 2 },
    { name: "join-patterns.md", type: "file", status: "unchanged", depth: 2 },

    // New top-level file
    { name: "general-guidelines.md", type: "file", status: "unchanged", depth: 1 },

    // Brand new folder
    { name: "Best Practices", type: "folder", status: "added", depth: 1, expanded: true },
    { name: "code-review-checklist.md", type: "file", status: "added", depth: 2 },
  ];
}

// ============================================================
// Context Menu
// ============================================================

interface ContextMenuState {
  x: number;
  y: number;
  targetId: string;
}

function ContextMenu({
  state,
  nodes,
  onClose,
  onCreateFile,
  onCreateFolder,
  onRename,
  onDelete,
}: {
  state: ContextMenuState;
  nodes: FSNode[];
  onClose: () => void;
  onCreateFile: (parentId: string) => void;
  onCreateFolder: (parentId: string) => void;
  onRename: (nodeId: string) => void;
  onDelete: (nodeId: string) => void;
}) {
  const target = nodes.find((n) => n.id === state.targetId);
  const isFolder = target?.type === "folder";
  const isRoot = target?.id === "root";

  useEffect(() => {
    const handler = () => onClose();
    window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [onClose]);

  return (
    <div
      className="priors-context-menu"
      style={{ top: state.y, left: state.x }}
      onClick={(e) => e.stopPropagation()}
    >
      {isFolder && (
        <>
          <button onClick={() => { onCreateFile(state.targetId); onClose(); }}>
            <Plus size={14} /> New File
          </button>
          <button onClick={() => { onCreateFolder(state.targetId); onClose(); }}>
            <FolderPlus size={14} /> New Folder
          </button>
          <div className="ctx-separator" />
        </>
      )}
      {!isRoot && (
        <>
          <button onClick={() => { onRename(state.targetId); onClose(); }}>
            <Pencil size={14} /> Rename
          </button>
          <button className="ctx-danger" onClick={() => { onDelete(state.targetId); onClose(); }}>
            <Trash2 size={14} /> Delete
          </button>
        </>
      )}
    </div>
  );
}

// ============================================================
// Confirmation Dialog
// ============================================================

function ConfirmDialog({
  message,
  onConfirm,
  onCancel,
}: {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="priors-dialog-overlay" onClick={onCancel}>
      <div className="priors-dialog" onClick={(e) => e.stopPropagation()}>
        <p>{message}</p>
        <div className="priors-dialog-actions">
          <button className="priors-dialog-cancel" onClick={onCancel}>Cancel</button>
          <button className="priors-dialog-confirm" onClick={onConfirm}>Delete</button>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// Rename Input
// ============================================================

function RenameInput({
  initialName,
  onSubmit,
  onCancel,
}: {
  initialName: string;
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initialName);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.select();
  }, []);

  return (
    <input
      ref={inputRef}
      className="priors-rename-input"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter" && value.trim()) onSubmit(value.trim());
        if (e.key === "Escape") onCancel();
      }}
      onBlur={() => {
        if (value.trim()) onSubmit(value.trim());
        else onCancel();
      }}
      autoFocus
    />
  );
}

// ============================================================
// Tree Node
// ============================================================

function TreeNode({
  node,
  nodes,
  depth,
  expanded,
  selected,
  multiSelected,
  renamingId,
  dragOverId,
  onToggle,
  onSelect,
  onContextMenu,
  onRenameSubmit,
  onRenameCancel,
  onDragStart,
  onDragOver,
  onDrop,
  onDragLeave,
}: {
  node: FSNode;
  nodes: FSNode[];
  depth: number;
  expanded: Set<string>;
  selected: string | null;
  multiSelected: Set<string>;
  renamingId: string | null;
  dragOverId: string | null;
  onToggle: (id: string) => void;
  onSelect: (id: string, e: React.MouseEvent) => void;
  onContextMenu: (id: string, e: React.MouseEvent) => void;
  onRenameSubmit: (id: string, name: string) => void;
  onRenameCancel: () => void;
  onDragStart: (id: string) => void;
  onDragOver: (id: string, e: React.DragEvent) => void;
  onDrop: (targetId: string) => void;
  onDragLeave: () => void;
}) {
  const isFolder = node.type === "folder";
  const isExpanded = expanded.has(node.id);
  const isSelected = node.id === selected;
  const isMultiSelected = multiSelected.has(node.id);
  const isDragOver = node.id === dragOverId && isFolder;
  const children = isFolder && isExpanded ? getChildren(nodes, node.id) : [];

  const cls = [
    "tree-node",
    isSelected ? "selected" : "",
    isMultiSelected ? "multi-selected" : "",
    isDragOver ? "drag-over" : "",
  ].filter(Boolean).join(" ");

  return (
    <>
      <div
        className={cls}
        style={{ paddingLeft: depth * 16 + 8 }}
        onClick={(e) => {
          if (isFolder) onToggle(node.id);
          onSelect(node.id, e);
        }}
        onContextMenu={(e) => onContextMenu(node.id, e)}
        draggable={node.id !== "root"}
        onDragStart={(e) => {
          e.dataTransfer.effectAllowed = "move";
          onDragStart(node.id);
        }}
        onDragOver={(e) => {
          if (isFolder) {
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            onDragOver(node.id, e);
          }
        }}
        onDrop={(e) => {
          e.preventDefault();
          if (isFolder) onDrop(node.id);
        }}
        onDragLeave={onDragLeave}
      >
        <span className={`tree-chevron${isFolder ? "" : " invisible"}`}>
          <ChevronRight size={14} className={isExpanded ? "rotated" : ""} />
        </span>
        {isFolder ? <Folder size={14} className="tree-icon folder-icon" /> : <FileText size={14} className="tree-icon file-icon" />}
        {renamingId === node.id ? (
          <RenameInput
            initialName={node.name}
            onSubmit={(name) => onRenameSubmit(node.id, name)}
            onCancel={onRenameCancel}
          />
        ) : (
          <span className="tree-label">{node.name}</span>
        )}
      </div>
      {children.map((child) => (
        <TreeNode
          key={child.id}
          node={child}
          nodes={nodes}
          depth={depth + 1}
          expanded={expanded}
          selected={selected}
          multiSelected={multiSelected}
          renamingId={renamingId}
          dragOverId={dragOverId}
          onToggle={onToggle}
          onSelect={onSelect}
          onContextMenu={onContextMenu}
          onRenameSubmit={onRenameSubmit}
          onRenameCancel={onRenameCancel}
          onDragStart={onDragStart}
          onDragOver={onDragOver}
          onDrop={onDrop}
          onDragLeave={onDragLeave}
        />
      ))}
    </>
  );
}

// ============================================================
// Diff Tree View
// ============================================================

function DiffTreeRow({ entry, active, onClick }: { entry: DiffEntry; active?: boolean; onClick?: () => void }) {
  const isFolder = entry.type === "folder";
  const isClickable = entry.type === "file" && entry.status !== "deleted";
  const cls = [
    "diff-row",
    `diff-${entry.status}`,
    isClickable ? "clickable" : "",
    active ? "active" : "",
  ].filter(Boolean).join(" ");

  return (
    <div
      className={cls}
      style={{ paddingLeft: entry.depth * 16 + 8 }}
      onClick={isClickable ? onClick : undefined}
    >
      <span className={`tree-chevron${isFolder ? "" : " invisible"}`}>
        <ChevronRight size={14} className={isFolder && entry.expanded ? "rotated" : ""} />
      </span>
      {isFolder
        ? <Folder size={14} className="tree-icon folder-icon" />
        : <FileText size={14} className="tree-icon file-icon" />
      }
      <span className="diff-row-name">{entry.name}</span>
      {entry.status === "modified" && <span className="diff-badge diff-badge-modified">M</span>}
    </div>
  );
}

function DiffPanel({
  diff,
  loading,
  activeFile,
  onGenerate,
  onClose,
  onApply,
  onFileClick,
}: {
  diff: DiffEntry[] | null;
  loading: boolean;
  activeFile: DiffEntry | null;
  onGenerate: () => void;
  onClose: () => void;
  onApply: () => void;
  onFileClick: (entry: DiffEntry) => void;
}) {
  return (
    <div className="diff-panel">
      <div className="diff-panel-header">
        <span className="diff-panel-title">Proposed Changes</span>
        <button className="taxonomy-close" onClick={onClose}><X size={14} /></button>
      </div>

      {!diff && !loading && (
        <div className="diff-panel-empty">
          <button className="taxonomy-generate-btn" onClick={onGenerate}>
            <Sparkles size={14} />
            Generate taxonomy
          </button>
          <p className="diff-panel-hint">AI will analyze your priors and suggest a reorganization.</p>
        </div>
      )}

      {loading && (
        <div className="diff-panel-loading">
          <Loader2 size={20} className="spin" />
          <span>Analyzing priors...</span>
        </div>
      )}

      {diff && !loading && (
        <>
          <div className="diff-tree">
            {diff.map((entry, i) => (
              <DiffTreeRow
                key={i}
                entry={entry}
                active={activeFile?.name === entry.name && activeFile?.status === entry.status}
                onClick={() => onFileClick(entry)}
              />
            ))}
          </div>
          <div className="diff-panel-footer">
            <div className="diff-panel-legend">
              <span className="diff-legend-item"><span className="diff-dot diff-dot-added" /> Added</span>
              <span className="diff-legend-item"><span className="diff-dot diff-dot-deleted" /> Deleted</span>
              <span className="diff-legend-item"><span className="diff-dot diff-dot-modified" /> Modified</span>
            </div>
            <div className="diff-panel-actions">
              <button className="diff-btn-discard" onClick={onClose}>Discard</button>
              <button className="diff-btn-apply" onClick={onApply}>Apply</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ============================================================
// Split Markdown Editor
// ============================================================

function SplitEditor({
  filename,
  value,
  onSave,
}: {
  filename: string;
  value: string;
  onSave: (value: string) => void;
}) {
  const [mode, setMode] = useState<"edit" | "preview" | "split">("split");
  const [draft, setDraft] = useState(value);
  const dirty = draft !== value;

  // Reset draft when switching files
  useEffect(() => { setDraft(value); }, [value]);

  const handleSave = () => { onSave(draft); };
  const handleDiscard = () => { setDraft(value); };

  return (
    <div className="split-editor">
      <div className="split-editor-toolbar">
        <div className="split-editor-tabs">
          <button className={mode === "edit" ? "active" : ""} onClick={() => setMode("edit")}>
            <PenLine size={14} /> Edit
          </button>
          <button className={mode === "split" ? "active" : ""} onClick={() => setMode("split")}>
            <FileText size={14} /> Split
          </button>
          <button className={mode === "preview" ? "active" : ""} onClick={() => setMode("preview")}>
            <Eye size={14} /> Preview
          </button>
        </div>
        <span className="split-editor-filename">
          {filename}
          {dirty && <span className="split-editor-dirty-dot" />}
        </span>
        {dirty && (
          <div className="split-editor-actions">
            <button className="split-editor-discard" onClick={handleDiscard} title="Discard changes">
              <X size={14} />
            </button>
            <button className="split-editor-save" onClick={handleSave} title="Save">
              <Check size={14} />
            </button>
          </div>
        )}
      </div>
      <div className={`split-editor-body mode-${mode}`}>
        {mode !== "preview" && (
          <textarea
            className="split-editor-textarea"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            spellCheck={false}
          />
        )}
        {mode !== "edit" && (
          <div className="split-editor-preview">
            <Markdown remarkPlugins={[remarkGfm]}>{mode === "split" ? draft : draft}</Markdown>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================
// Diff File Viewer (inline diff for modified files, preview for new)
// ============================================================

function DiffLine({ type, text }: { type: "add" | "remove" | "context"; text: string }) {
  const prefix = type === "add" ? "+" : type === "remove" ? "−" : " ";
  return (
    <div className={`diff-line diff-line-${type}`}>
      <span className="diff-line-prefix">{prefix}</span>
      <span className="diff-line-text">{text}</span>
    </div>
  );
}

function computeLineDiff(original: string, proposed: string): { type: "add" | "remove" | "context"; text: string }[] {
  const origLines = original.split("\n");
  const propLines = proposed.split("\n");

  // Simple LCS-based diff
  const m = origLines.length, n = propLines.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = origLines[i - 1] === propLines[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);

  let i = m, j = n;
  const result: { type: "add" | "remove" | "context"; text: string }[] = [];
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && origLines[i - 1] === propLines[j - 1]) {
      result.push({ type: "context", text: origLines[i - 1] });
      i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.push({ type: "add", text: propLines[j - 1] });
      j--;
    } else {
      result.push({ type: "remove", text: origLines[i - 1] });
      i--;
    }
  }
  return result.reverse();
}

function DiffFileViewer({ entry, nodes }: { entry: DiffEntry; nodes: FSNode[] }) {
  const fileData = DIFF_FILE_CONTENT[entry.name];

  // For unchanged files, look up content from the filesystem
  const fsContent = !fileData
    ? nodes.find((n) => n.type === "file" && n.name === entry.name)?.content
    : undefined;

  const isModified = entry.status === "modified" && fileData?.original;
  const diffLines = isModified ? computeLineDiff(fileData!.original!, fileData!.proposed) : null;

  // Determine content for preview/edit modes
  const previewContent = fileData?.proposed ?? fsContent ?? "";

  type DiffViewMode = "diff" | "edit" | "split" | "preview";
  const defaultMode: DiffViewMode = isModified ? "diff" : "preview";
  const [mode, setMode] = useState<DiffViewMode>(defaultMode);

  return (
    <div className="split-editor">
      <div className="split-editor-toolbar">
        <div className="split-editor-tabs">
          {isModified && (
            <button className={mode === "diff" ? "active" : ""} onClick={() => setMode("diff")}>
              <FileText size={14} /> Diff
            </button>
          )}
          <button className={mode === "edit" ? "active" : ""} onClick={() => setMode("edit")}>
            <PenLine size={14} /> Edit
          </button>
          <button className={mode === "split" ? "active" : ""} onClick={() => setMode("split")}>
            <FileText size={14} /> Split
          </button>
          <button className={mode === "preview" ? "active" : ""} onClick={() => setMode("preview")}>
            <Eye size={14} /> Preview
          </button>
        </div>
        <span className="split-editor-filename">
          {entry.name}
          {isModified && <span className="diff-badge diff-badge-modified" style={{ marginLeft: 6 }}>M</span>}
        </span>
      </div>
      <div className={`split-editor-body mode-${mode === "diff" ? "preview" : mode}`}>
        {mode === "diff" && diffLines ? (
          <div className="diff-file-lines" style={{ flex: 1, overflowY: "auto" }}>
            {diffLines.map((line, i) => (
              <DiffLine key={i} type={line.type} text={line.text} />
            ))}
          </div>
        ) : (
          <>
            {mode !== "preview" && mode !== "diff" && (
              <textarea
                className="split-editor-textarea"
                defaultValue={previewContent}
                readOnly
                spellCheck={false}
              />
            )}
            {mode !== "edit" && mode !== "diff" && (
              <div className="split-editor-preview">
                <Markdown remarkPlugins={[remarkGfm]}>{previewContent}</Markdown>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ============================================================
// Main Page
// ============================================================

export function PriorsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const project = mockProjects.find((p) => p.id === projectId);

  // Filesystem state
  const [nodes, setNodes] = useState<FSNode[]>(() => createMockFilesystem());
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(["root"]));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [multiSelected, setMultiSelected] = useState<Set<string>>(new Set());

  // UI state
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [dragSource, setDragSource] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  // Diff state
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffResult, setDiffResult] = useState<DiffEntry[] | null>(null);
  const [diffViewingFile, setDiffViewingFile] = useState<DiffEntry | null>(null);

  // Editor content (derived from selected file)
  const selectedNode = selectedId ? nodes.find((n) => n.id === selectedId) : null;
  const editorContent = selectedNode?.type === "file" ? (selectedNode.content ?? "") : "";

  // ----------------------------------------------------------
  // Handlers
  // ----------------------------------------------------------

  const onToggle = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const onSelect = useCallback((id: string, e: React.MouseEvent) => {
    if (e.metaKey || e.ctrlKey) {
      setMultiSelected((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
    } else {
      setSelectedId(id);
      setMultiSelected(new Set());
    }
  }, []);

  const onContextMenu = useCallback((id: string, e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, targetId: id });
  }, []);

  const onCreateFile = useCallback((parentId: string) => {
    const name = prompt("File name (e.g. my-prior.md):");
    if (!name?.trim()) return;
    const newNode: FSNode = { id: genId(), name: name.trim(), type: "file", parentId, content: `# ${name.trim().replace(/\.md$/, "")}\n\nWrite your prior here.\n` };
    setNodes((prev) => [...prev, newNode]);
    setExpanded((prev) => new Set(prev).add(parentId));
    setSelectedId(newNode.id);
  }, []);

  const onCreateFolder = useCallback((parentId: string) => {
    const name = prompt("Folder name:");
    if (!name?.trim()) return;
    const newNode: FSNode = { id: genId(), name: name.trim(), type: "folder", parentId };
    setNodes((prev) => [...prev, newNode]);
    setExpanded((prev) => new Set(prev).add(parentId));
  }, []);

  const onRenameSubmit = useCallback((id: string, name: string) => {
    setNodes((prev) => prev.map((n) => (n.id === id ? { ...n, name } : n)));
    setRenamingId(null);
  }, []);

  const onDelete = useCallback((id: string) => {
    setDeleteTarget(id);
  }, []);

  const confirmDelete = useCallback(() => {
    if (!deleteTarget) return;
    const descendantIds = getAllDescendantIds(nodes, deleteTarget);
    const idsToRemove = new Set([deleteTarget, ...descendantIds]);
    setNodes((prev) => prev.filter((n) => !idsToRemove.has(n.id)));
    if (selectedId && idsToRemove.has(selectedId)) setSelectedId(null);
    setMultiSelected((prev) => {
      const next = new Set(prev);
      for (const id of idsToRemove) next.delete(id);
      return next;
    });
    setDeleteTarget(null);
  }, [deleteTarget, nodes, selectedId]);

  const onEditorSave = useCallback((value: string) => {
    if (selectedId) {
      setNodes((prev) => prev.map((n) => (n.id === selectedId ? { ...n, content: value } : n)));
    }
  }, [selectedId]);

  // Drag and drop
  const onDragStart = useCallback((id: string) => setDragSource(id), []);
  const onDragOver = useCallback((id: string) => setDragOverId(id), []);
  const onDragLeave = useCallback(() => setDragOverId(null), []);
  const onDrop = useCallback((targetId: string) => {
    setDragOverId(null);
    if (!dragSource || dragSource === targetId) return;
    const descendants = getAllDescendantIds(nodes, dragSource);
    if (descendants.includes(targetId)) return;
    setNodes((prev) => prev.map((n) => (n.id === dragSource ? { ...n, parentId: targetId } : n)));
    setExpanded((prev) => new Set(prev).add(targetId));
    setDragSource(null);
  }, [dragSource, nodes]);

  // Taxonomy diff
  const onGenerateDiff = useCallback(() => {
    setDiffLoading(true);
    setDiffResult(null);
    setTimeout(() => {
      setDiffLoading(false);
      setDiffResult(generateMockDiff());
    }, 1800);
  }, []);

  const onCloseDiff = useCallback(() => {
    setDiffOpen(false);
    setDiffResult(null);
    setDiffLoading(false);
    setDiffViewingFile(null);
  }, []);

  const onApplyDiff = useCallback(() => {
    // In a real app this would apply the diff to the filesystem
    // For now just close the panel
    onCloseDiff();
  }, [onCloseDiff]);

  // ----------------------------------------------------------
  // Breadcrumb
  // ----------------------------------------------------------

  const breadcrumbItems = [
    { label: project?.name ?? "Project", onClick: () => navigate(`/project/${projectId}`) },
    { label: "Priors" },
  ];

  // ----------------------------------------------------------
  // Render
  // ----------------------------------------------------------

  const rootNode = nodes.find((n) => n.id === "root");
  const deleteNode = deleteTarget ? nodes.find((n) => n.id === deleteTarget) : null;

  return (
    <div className="priors-page">
      <Breadcrumb items={breadcrumbItems} />

      <div className="priors-body">
        {/* Left: File Explorer */}
        <div className="priors-explorer">
          <div className="priors-explorer-header">
            <span className="priors-explorer-title">Priors</span>
            <div className="priors-explorer-actions">
              <button title="New File" onClick={() => onCreateFile(selectedNode?.type === "folder" ? selectedId! : selectedNode?.parentId ?? "root")}>
                <Plus size={14} />
              </button>
              <button title="New Folder" onClick={() => onCreateFolder(selectedNode?.type === "folder" ? selectedId! : selectedNode?.parentId ?? "root")}>
                <FolderPlus size={14} />
              </button>
            </div>
          </div>

          <button
            className="taxonomy-generate-btn-inline"
            onClick={() => { setDiffOpen(true); if (!diffResult) onGenerateDiff(); }}
            disabled={diffLoading}
          >
            <Sparkles size={14} />
            {diffLoading ? "Generating..." : "Reorganize with AI"}
          </button>

          <div className="priors-tree">
            {rootNode && (
              <TreeNode
                node={rootNode}
                nodes={nodes}
                depth={0}
                expanded={expanded}
                selected={selectedId}
                multiSelected={multiSelected}
                renamingId={renamingId}
                dragOverId={dragOverId}
                onToggle={onToggle}
                onSelect={onSelect}
                onContextMenu={onContextMenu}
                onRenameSubmit={onRenameSubmit}
                onRenameCancel={() => setRenamingId(null)}
                onDragStart={onDragStart}
                onDragOver={onDragOver}
                onDrop={onDrop}
                onDragLeave={onDragLeave}
              />
            )}
          </div>
        </div>

        {/* Diff panel (between explorer and editor) */}
        {diffOpen && (
          <DiffPanel
            diff={diffResult}
            loading={diffLoading}
            activeFile={diffViewingFile}
            onGenerate={onGenerateDiff}
            onClose={onCloseDiff}
            onApply={onApplyDiff}
            onFileClick={(entry) => setDiffViewingFile(entry)}
          />
        )}

        {/* Right: Editor */}
        <div className="priors-editor-panel">
          {diffViewingFile ? (
            <DiffFileViewer key={diffViewingFile.name} entry={diffViewingFile} nodes={nodes} />
          ) : selectedNode?.type === "file" ? (
            <SplitEditor
              key={selectedId!}
              filename={selectedNode.name}
              value={editorContent}
              onSave={onEditorSave}
            />
          ) : (
            <div className="priors-editor-empty">
              <FileText size={32} />
              <p>Select a file to edit</p>
            </div>
          )}
        </div>
      </div>

      {/* Context Menu */}
      {contextMenu && (
        <ContextMenu
          state={contextMenu}
          nodes={nodes}
          onClose={() => setContextMenu(null)}
          onCreateFile={onCreateFile}
          onCreateFolder={onCreateFolder}
          onRename={(id) => setRenamingId(id)}
          onDelete={onDelete}
        />
      )}

      {/* Delete Confirmation */}
      {deleteTarget && deleteNode && (
        <ConfirmDialog
          message={`Delete "${deleteNode.name}"${deleteNode.type === "folder" ? " and all its contents" : ""}?`}
          onConfirm={confirmDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
