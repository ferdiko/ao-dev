import { useState, useMemo, useCallback, useEffect } from "react";
import { useParams } from "react-router-dom";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Sparkles,
  Loader2,
  ChevronUp,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Eye,
  PenLine,
  FileText,
  Send,
  Folder,
  X,
  MessageSquareWarning,
  Check,
  ShieldAlert,
} from "lucide-react";
import { mockProjects } from "../data/mock";
import { mockFailureAnalyses, type FailureAnalysis } from "../data/failure-analysis-mock";
import { createMockFilesystem, type FSNode } from "../data/priors-mock";
import { Breadcrumb } from "../components/Breadcrumb";

// ── Sorting ──────────────────────────────────────────────

type SortDirection = "asc" | "desc";
type SortState = { key: string; direction: SortDirection } | null;

function compareAnalyses(a: FailureAnalysis, b: FailureAnalysis, key: string): number {
  switch (key) {
    case "startTime": return a.startTime.localeCompare(b.startTime);
    case "analysisId": return a.analysisId.localeCompare(b.analysisId);
    case "sessionId": return a.sessionId.localeCompare(b.sessionId);
    case "name": return a.name.localeCompare(b.name);
    case "input": return a.input.localeCompare(b.input);
    case "output": return (a.output || "").localeCompare(b.output || "");
    case "version": return a.version.localeCompare(b.version);
    case "status": return a.status.localeCompare(b.status);
    default: return 0;
  }
}

function sortAnalyses(analyses: FailureAnalysis[], sort: SortState): FailureAnalysis[] {
  if (!sort) return analyses;
  const sorted = [...analyses].sort((a, b) => compareAnalyses(a, b, sort.key));
  return sort.direction === "desc" ? sorted.reverse() : sorted;
}

function SortableHeader({
  label,
  sortKey,
  sort,
  onSort,
}: {
  label: string;
  sortKey: string;
  sort: SortState;
  onSort: (key: string) => void;
}) {
  const active = sort?.key === sortKey;
  return (
    <th
      className={`sortable-th${active ? " sorted" : ""}`}
      onClick={() => onSort(sortKey)}
    >
      <span className="th-sort-content">
        {label}
        {active && (
          sort.direction === "asc"
            ? <ChevronUp size={12} className="sort-icon" />
            : <ChevronDown size={12} className="sort-icon" />
        )}
      </span>
    </th>
  );
}

// ── Pagination ───────────────────────────────────────────

const ROWS_PER_PAGE_OPTIONS = [10, 20, 50, 100];

function PaginationBar({
  rowsPerPage,
  setRowsPerPage,
  currentPage,
  setCurrentPage,
  totalPages,
}: {
  rowsPerPage: number;
  setRowsPerPage: (n: number) => void;
  currentPage: number;
  setCurrentPage: (n: number) => void;
  totalPages: number;
}) {
  return (
    <div className="pagination-bar">
      <div className="pagination-rows-per-page">
        <span>Rows per page</span>
        <select
          value={rowsPerPage}
          onChange={(e) => {
            setRowsPerPage(Number(e.target.value));
            setCurrentPage(1);
          }}
        >
          {ROWS_PER_PAGE_OPTIONS.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </div>
      <div className="pagination-nav">
        <span className="pagination-info">
          Page {currentPage} of {totalPages}
        </span>
        <button className="pagination-btn" disabled={currentPage <= 1} onClick={() => setCurrentPage(1)}>
          <ChevronsLeft size={16} />
        </button>
        <button className="pagination-btn" disabled={currentPage <= 1} onClick={() => setCurrentPage(currentPage - 1)}>
          <ChevronLeft size={16} />
        </button>
        <button className="pagination-btn" disabled={currentPage >= totalPages} onClick={() => setCurrentPage(currentPage + 1)}>
          <ChevronRight size={16} />
        </button>
        <button className="pagination-btn" disabled={currentPage >= totalPages} onClick={() => setCurrentPage(totalPages)}>
          <ChevronsRight size={16} />
        </button>
      </div>
    </div>
  );
}

// ── Types ────────────────────────────────────────────────

interface SubmissionFeedback {
  status: "success" | "reject";
  comments: string;
}

// ── Prior Split Editor ───────────────────────────────────

type EditorMode = "edit" | "split" | "preview" | "feedback";

function PriorSplitEditor({
  content,
  onChange,
  feedback,
  initialMode,
}: {
  content: string;
  onChange: (value: string) => void;
  feedback?: SubmissionFeedback | null;
  initialMode?: EditorMode;
}) {
  const [mode, setMode] = useState<EditorMode>(initialMode ?? "split");

  // Switch to feedback tab when new feedback arrives
  useEffect(() => {
    if (feedback) setMode("feedback");
  }, [feedback]);

  return (
    <div className="fa-prior-editor">
      <div className="fa-prior-editor-tabs">
        <button className={mode === "edit" ? "active" : ""} onClick={() => setMode("edit")}>
          <PenLine size={13} /> Edit
        </button>
        <button className={mode === "split" ? "active" : ""} onClick={() => setMode("split")}>
          <FileText size={13} /> Split
        </button>
        <button className={mode === "preview" ? "active" : ""} onClick={() => setMode("preview")}>
          <Eye size={13} /> Preview
        </button>
        {feedback && (
          <button
            className={`${mode === "feedback" ? "active" : ""} fa-feedback-tab fa-feedback-tab-${feedback.status}`}
            onClick={() => setMode("feedback")}
          >
            {feedback.status === "reject"
              ? <><ShieldAlert size={13} /> Feedback</>
              : <><Check size={13} /> Feedback</>
            }
          </button>
        )}
      </div>
      <div className={`fa-prior-editor-body fa-prior-mode-${mode === "feedback" ? "preview" : mode}`}>
        {mode === "feedback" && feedback ? (
          <div className="fa-prior-preview">
            <div className={`fa-feedback-banner fa-feedback-${feedback.status}`}>
              {feedback.status === "reject" ? (
                <><ShieldAlert size={14} /> Submission rejected</>
              ) : (
                <><Check size={14} /> Submission accepted</>
              )}
            </div>
            <div className="fa-feedback-comments">
              <Markdown remarkPlugins={[remarkGfm]}>{feedback.comments}</Markdown>
            </div>
          </div>
        ) : (
          <>
            {mode !== "preview" && (
              <textarea
                className="fa-prior-textarea"
                value={content}
                onChange={(e) => onChange(e.target.value)}
                spellCheck={false}
                placeholder="Write your prior here…"
              />
            )}
            {mode !== "edit" && (
              <div className="fa-prior-preview">
                {content ? (
                  <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
                ) : (
                  <span className="fa-prior-preview-empty">No content yet.</span>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Folder Picker Dialog ─────────────────────────────────

function getChildFolders(nodes: FSNode[], parentId: string): FSNode[] {
  return nodes
    .filter((n) => n.parentId === parentId && n.type === "folder")
    .sort((a, b) => a.name.localeCompare(b.name));
}

function getChildFiles(nodes: FSNode[], parentId: string): FSNode[] {
  return nodes
    .filter((n) => n.parentId === parentId && n.type === "file")
    .sort((a, b) => a.name.localeCompare(b.name));
}

function FolderTreeNode({
  node,
  nodes,
  depth,
  expanded,
  selected,
  onToggle,
  onSelect,
}: {
  node: FSNode;
  nodes: FSNode[];
  depth: number;
  expanded: Set<string>;
  selected: string | null;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
}) {
  const isExpanded = expanded.has(node.id);
  const childFolders = isExpanded ? getChildFolders(nodes, node.id) : [];
  const childFiles = isExpanded ? getChildFiles(nodes, node.id) : [];
  const hasChildren = getChildFolders(nodes, node.id).length > 0 || getChildFiles(nodes, node.id).length > 0;

  return (
    <>
      <div
        className={`fp-tree-node${node.id === selected ? " fp-selected" : ""}`}
        style={{ paddingLeft: depth * 16 + 8 }}
        onClick={() => {
          onSelect(node.id);
          if (hasChildren) onToggle(node.id);
        }}
      >
        <span className={`tree-chevron${hasChildren ? "" : " invisible"}`}>
          <ChevronRight size={14} className={isExpanded ? "rotated" : ""} />
        </span>
        <Folder size={14} className="tree-icon folder-icon" />
        <span className="tree-label">{node.name}</span>
      </div>
      {childFolders.map((child) => (
        <FolderTreeNode
          key={child.id}
          node={child}
          nodes={nodes}
          depth={depth + 1}
          expanded={expanded}
          selected={selected}
          onToggle={onToggle}
          onSelect={onSelect}
        />
      ))}
      {childFiles.map((f) => (
        <div
          key={f.id}
          className="fp-tree-node fp-file-node"
          style={{ paddingLeft: (depth + 1) * 16 + 8 }}
        >
          <span className="tree-chevron invisible">
            <ChevronRight size={14} />
          </span>
          <FileText size={14} className="tree-icon file-icon" />
          <span className="tree-label">{f.name}</span>
        </div>
      ))}
    </>
  );
}

function FolderPickerDialog({
  onSubmit,
  onCancel,
}: {
  onSubmit: (folderPath: string) => void;
  onCancel: () => void;
}) {
  const [fsNodes] = useState(() => createMockFilesystem());
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(["root"]));
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);

  const rootNode = fsNodes.find((n) => n.id === "root");

  const onToggle = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // Build folder path from selected ID
  const buildPath = useCallback((folderId: string): string => {
    const parts: string[] = [];
    let current = fsNodes.find((n) => n.id === folderId);
    while (current) {
      parts.unshift(current.name);
      current = current.parentId ? fsNodes.find((n) => n.id === current!.parentId) : undefined;
    }
    return parts.join("/");
  }, [fsNodes]);

  return (
    <div className="fp-overlay" onClick={onCancel}>
      <div className="fp-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="fp-dialog-header">
          <span className="fp-dialog-title">Select folder</span>
          <button className="fp-dialog-close" onClick={onCancel}><X size={14} /></button>
        </div>
        <div className="fp-dialog-body">
          <div className="fp-tree">
            {rootNode && (
              <FolderTreeNode
                node={rootNode}
                nodes={fsNodes}
                depth={0}
                expanded={expanded}
                selected={selectedFolder}
                onToggle={onToggle}
                onSelect={setSelectedFolder}
              />
            )}
          </div>
        </div>
        <div className="fp-dialog-footer">
          <button className="fp-btn-cancel" onClick={onCancel}>Cancel</button>
          <button
            className="fp-btn-submit"
            disabled={!selectedFolder}
            onClick={() => selectedFolder && onSubmit(buildPath(selectedFolder))}
          >
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────

const MOCK_PROPOSED_PRIOR = `### Prior: Verify column existence before generating SQL

**When**: Generating SQL queries that reference specific column names.

**Rule**: Always verify that referenced column names exist in the table schema before including them in the generated query. If the schema retrieval step only returns table names, request column-level detail before proceeding.

**Rationale**: The agent hallucinated a \`revenue\` column that does not exist on the \`sales\` table. Revenue must be computed as \`quantity * unit_price\`.
`;

export function AIFailureAnalysisPage() {
  const { projectId } = useParams();
  const project = mockProjects.find((p) => p.id === projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sort, setSort] = useState<SortState>({ key: "startTime", direction: "desc" });

  // Pagination
  const [rowsPerPage, setRowsPerPage] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);

  // Prior content per analysis (id -> content)
  const [priorContents, setPriorContents] = useState<Record<string, string>>({});

  // Folder picker dialog
  const [showFolderPicker, setShowFolderPicker] = useState(false);

  // Propose Prior loading state
  const [proposing, setProposing] = useState(false);
  // Track which analyses have AI-generated priors
  const [aiGenerated, setAiGenerated] = useState<Record<string, boolean>>({});
  // Submission feedback per analysis
  const [feedbacks, setFeedbacks] = useState<Record<string, SubmissionFeedback>>({});
  // Submitting state
  const [submitting, setSubmitting] = useState(false);

  const handleProposePrior = useCallback(() => {
    if (!selectedId) return;
    setProposing(true);
    // Clear previous feedback when re-proposing
    setFeedbacks((prev) => { const next = { ...prev }; delete next[selectedId]; return next; });
    // Simulate AI generation delay
    setTimeout(() => {
      setPriorContents((prev) => ({ ...prev, [selectedId]: MOCK_PROPOSED_PRIOR }));
      setAiGenerated((prev) => ({ ...prev, [selectedId]: true }));
      setProposing(false);
    }, 1500);
  }, [selectedId]);

  const handleSubmitPrior = useCallback((folderPath: string, force = false) => {
    if (!selectedId) return;
    setShowFolderPicker(false);
    setSubmitting(true);
    // Simulate server response
    setTimeout(() => {
      if (force) {
        // Force submit always succeeds
        setFeedbacks((prev) => ({
          ...prev,
          [selectedId]: {
            status: "success",
            comments: "Prior force-submitted successfully. It will be included in the next evaluation cycle.",
          },
        }));
      } else {
        // First submission gets rejected with feedback
        const existing = feedbacks[selectedId];
        if (!existing || existing.status === "reject") {
          setFeedbacks((prev) => ({
            ...prev,
            [selectedId]: {
              status: "reject",
              comments: "**Overlap detected**: A prior with similar content already exists in `SQL Best Practices/query-optimization.md`.\n\nConsider:\n- Merging this prior with the existing one\n- Narrowing the scope to focus specifically on column existence validation\n- Adding a cross-reference to the existing prior instead",
            },
          }));
        } else {
          setFeedbacks((prev) => ({
            ...prev,
            [selectedId]: {
              status: "success",
              comments: "Prior submitted successfully to `" + folderPath + "`. It will be included in the next evaluation cycle.",
            },
          }));
        }
      }
      setSubmitting(false);
    }, 1200);
  }, [selectedId, feedbacks]);

  const toggleSort = useCallback((key: string) => {
    setSort((prev) => {
      if (prev?.key === key) {
        return prev.direction === "asc" ? { key, direction: "desc" } : null;
      }
      return { key, direction: "asc" };
    });
  }, []);

  const sorted = useMemo(() => sortAnalyses(mockFailureAnalyses, sort), [sort]);
  const totalPages = Math.max(1, Math.ceil(sorted.length / rowsPerPage));
  const paginated = sorted.slice((currentPage - 1) * rowsPerPage, currentPage * rowsPerPage);

  const selected = selectedId
    ? mockFailureAnalyses.find((a) => a.id === selectedId) ?? null
    : null;

  const selectedPrior = selected ? (priorContents[selected.id] ?? "") : "";

  if (!project) return <div>Project not found</div>;

  return (
    <div className="page-wrapper">
      <Breadcrumb
        items={[
          { label: "Organization", to: "/" },
          { label: project.name, to: `/project/${projectId}` },
          { label: "AI Failure Analysis" },
        ]}
      />

      <div className="project-page-header">
        <div className="project-page-title">AI Failure Analysis</div>
      </div>

      <div className="fa-layout">
        {/* ── Left panel: table (top) + failure report (bottom) ── */}
        <div className="fa-left">
          {/* Top: Analyses table */}
          <div className="fa-table-panel">
            <div className="runs-section">
              <div className="landing-section-title">
                <span>Analyses ({mockFailureAnalyses.length})</span>
              </div>
              <div className="runs-section-scroll">
                <table className="runs-table">
                  <thead>
                    <tr>
                      <SortableHeader label="Status" sortKey="status" sort={sort} onSort={toggleSort} />
                      <SortableHeader label="Start Time" sortKey="startTime" sort={sort} onSort={toggleSort} />
                      <SortableHeader label="Analysis ID" sortKey="analysisId" sort={sort} onSort={toggleSort} />
                      <SortableHeader label="Session ID" sortKey="sessionId" sort={sort} onSort={toggleSort} />
                      <SortableHeader label="Name" sortKey="name" sort={sort} onSort={toggleSort} />
                      <SortableHeader label="Input" sortKey="input" sort={sort} onSort={toggleSort} />
                      <SortableHeader label="Output" sortKey="output" sort={sort} onSort={toggleSort} />
                      <SortableHeader label="Version" sortKey="version" sort={sort} onSort={toggleSort} />
                    </tr>
                  </thead>
                  <tbody>
                    {paginated.map((a) => (
                      <tr
                        key={a.id}
                        className={selectedId === a.id ? "row-selected" : ""}
                        onClick={() => setSelectedId(a.id)}
                        style={{ cursor: "pointer" }}
                      >
                        <td>
                          <span className={`fa-status fa-status-${a.status}`}>
                            {a.status === "running" ? (
                              <><Loader2 size={12} className="fa-spinner" /> Running</>
                            ) : (
                              "Completed"
                            )}
                          </span>
                        </td>
                        <td className="cell-timestamp">{a.startTime}</td>
                        <td><span className="cell-id-link">{a.analysisId}</span></td>
                        <td><span className="cell-id-link">{a.sessionId}</span></td>
                        <td>{a.name}</td>
                        <td className="cell-content">{a.input}</td>
                        <td className="cell-content">{a.output || "—"}</td>
                        <td><span className="cell-id-link">{a.version}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <PaginationBar
                rowsPerPage={rowsPerPage}
                setRowsPerPage={setRowsPerPage}
                currentPage={currentPage}
                setCurrentPage={setCurrentPage}
                totalPages={totalPages}
              />
            </div>
          </div>

          {/* Bottom: Prior editor */}
          <div className="fa-prior-panel">
            <div className="fa-panel-header">
              <span className="fa-panel-title">
                Prior
                {selected && <span className="fa-analysis-id-badge">{selected.analysisId}</span>}
              </span>
              <div className="fa-panel-header-actions">
                {selected?.status === "completed" && (
                  <button
                    className="fa-propose-btn"
                    disabled={proposing || submitting}
                    onClick={handleProposePrior}
                  >
                    {proposing
                      ? <><Loader2 size={13} className="fa-spinner" /> Proposing…</>
                      : <><Sparkles size={13} /> Propose Prior</>
                    }
                  </button>
                )}
                {selected?.status === "completed" && (
                  <button
                    className="fa-submit-btn"
                    disabled={submitting || !selectedPrior}
                    onClick={() => setShowFolderPicker(true)}
                  >
                    {submitting
                      ? <><Loader2 size={13} className="fa-spinner" /> Submitting…</>
                      : <><Send size={13} /> Submit Prior</>
                    }
                  </button>
                )}
                {selected && feedbacks[selected.id]?.status === "reject" && (
                  <button
                    className="fa-force-submit-btn"
                    disabled={submitting}
                    onClick={() => handleSubmitPrior("", true)}
                  >
                    <ShieldAlert size={13} />
                    Force Submit
                  </button>
                )}
              </div>
            </div>
            <div className="fa-prior-content">
              {!selected ? (
                <div className="fa-panel-empty">
                  Select an analysis to create a prior
                </div>
              ) : proposing ? (
                <div className="fa-panel-empty">
                  <Loader2 size={20} className="fa-spinner" />
                  <span>Generating prior…</span>
                </div>
              ) : selected.status === "running" ? (
                <div className="fa-panel-empty">
                  Waiting for analysis to complete…
                </div>
              ) : (
                <>
                  {aiGenerated[selected.id] && (
                    <div className="fa-ai-badge">
                      <Sparkles size={12} />
                      AI-generated prior — review and edit before submitting
                    </div>
                  )}
                  <PriorSplitEditor
                    key={selected.id}
                    content={selectedPrior}
                    onChange={(val) => setPriorContents((prev) => ({ ...prev, [selected.id]: val }))}
                    feedback={feedbacks[selected.id] ?? null}
                    initialMode={selectedPrior ? "split" : "edit"}
                  />
                </>
              )}
            </div>
          </div>
        </div>

        {/* ── Right panel: Failure report (full height) ── */}
        <div className="fa-right">
          <div className="fa-report-panel">
            <div className="fa-panel-header">
              <span className="fa-panel-title">
                Failure Report
                {selected && <span className="fa-analysis-id-badge">{selected.analysisId}</span>}
              </span>
              {selected?.status === "running" && (
                <span className="fa-panel-status"><Loader2 size={13} className="fa-spinner" /> Generating…</span>
              )}
            </div>
            <div className="fa-report-content">
              {!selected ? (
                <div className="fa-panel-empty">
                  Select an analysis to view the failure report
                </div>
              ) : selected.report ? (
                <Markdown remarkPlugins={[remarkGfm]}>{selected.report}</Markdown>
              ) : (
                <div className="fa-panel-empty">
                  <Loader2 size={20} className="fa-spinner" />
                  <span>Analysis in progress…</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Folder picker dialog */}
      {showFolderPicker && (
        <FolderPickerDialog
          onSubmit={(folderPath) => handleSubmitPrior(folderPath)}
          onCancel={() => setShowFolderPicker(false)}
        />
      )}
    </div>
  );
}
