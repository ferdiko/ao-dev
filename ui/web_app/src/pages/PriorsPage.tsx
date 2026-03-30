import {
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useParams } from "react-router-dom";
import {
  ArrowRightLeft,
  Check,
  ChevronRight,
  ClipboardPaste,
  Copy,
  Eye,
  FileText,
  Folder,
  FolderPlus,
  Loader2,
  PenLine,
  Pencil,
  Plus,
  ShieldAlert,
  Trash2,
  X,
} from "lucide-react";

import {
  copyPriorItems,
  createDraftPrior,
  createPriorFolder,
  deletePriorItems,
  fetchPrior,
  fetchPriorsFolder,
  fetchProject,
  movePriorFolder,
  movePriorItems,
  submitPrior,
  updatePrior,
  type FolderLsResponse,
  type PriorItemRef,
  type PriorRecord,
  type PriorValidationDetail,
} from "../api";
import { Breadcrumb } from "../components/Breadcrumb";
import { RenderedMarkdown } from "../components/RenderedMarkdown";
import { subscribe } from "../serverEvents";

type FolderMap = Record<string, FolderLsResponse>;

type DraftPrior = {
  key: string;
  kind: "prior";
  name: string;
  path: string;
  content: string;
};

type DraftFolder = {
  key: string;
  kind: "folder";
  name: string;
  parentPath: string;
};

type DraftItem = DraftPrior | DraftFolder;

type ExplorerRow = {
  key: string;
  kind: "prior" | "folder";
  name: string;
  depth: number;
  path: string;
  parentPath: string;
  isDraft: boolean;
  expanded?: boolean;
  prior?: PriorRecord;
  draft?: DraftItem;
};

type ContextMenuAction = {
  label: string;
  icon: typeof Plus;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
};

type ContextMenuState = {
  x: number;
  y: number;
  selectionKeys: string[];
  backgroundPath: string;
};

type DeleteDialogState = {
  keys: string[];
};

type MoveDialogState = {
  keys: string[];
  destinationPath: string;
};

type SystemToastState = {
  id: number;
  message: string;
};

type EditorPrior = PriorRecord & {
  draftKey?: string;
};

function normalizeError(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return String(error ?? "Unknown error");
}

function isConnectivityError(message: string): boolean {
  const normalized = message.toLowerCase();
  return (
    normalized.includes("failed to fetch")
    || normalized.includes("connect")
    || normalized.includes("connection failed")
    || normalized.includes("refused")
    || normalized.includes("timeout")
    || normalized.includes("unavailable")
    || normalized.includes("networkerror")
  );
}

function normalizeFolderPath(path: string): string {
  const cleaned = (path || "").trim().replace(/^\/+|\/+$/g, "");
  return cleaned ? `${cleaned}/` : "";
}

function getFolderName(path: string): string {
  const normalized = normalizeFolderPath(path);
  if (!normalized) return "";
  const parts = normalized.split("/").filter(Boolean);
  return parts[parts.length - 1] || "";
}

function getParentFolderPath(path: string): string {
  const parts = normalizeFolderPath(path).split("/").filter(Boolean);
  if (parts.length <= 1) return "";
  return `${parts.slice(0, -1).join("/")}/`;
}

function joinFolderPath(parentPath: string, name: string): string {
  const normalizedName = name.trim().replace(/^\/+|\/+$/g, "");
  const normalizedParent = normalizeFolderPath(parentPath);
  return normalizeFolderPath(normalizedParent ? `${normalizedParent}${normalizedName}` : normalizedName);
}

function displayPriorName(name: string): string {
  return name.toLowerCase().endsWith(".md") ? name : `${name}.md`;
}

function priorStem(name: string): string {
  return name.trim().replace(/\.md$/i, "");
}

function prettyName(name: string): string {
  const stem = priorStem(name);
  return stem
    .split(/[-_]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function seedMarkdown(name: string): string {
  const title = prettyName(name) || "New Prior";
  return `# ${title}\n\nWrite the prior here.\n`;
}

function folderRowKey(path: string): string {
  return `folder:${normalizeFolderPath(path)}`;
}

function priorRowKey(priorId: string): string {
  return `prior:${priorId}`;
}

function createDraftKey(prefix: string): string {
  const randomId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${randomId}`;
}

function sortByName<T extends { name: string }>(items: T[]): T[] {
  return [...items].sort((left, right) => left.name.localeCompare(right.name, undefined, {
    numeric: true,
    sensitivity: "base",
  }));
}

function buildValidationResult(
  validation: PriorValidationDetail | undefined,
  reason: string | undefined,
  conflictingPriorIds: string[] | undefined,
): PriorValidationDetail {
  if (validation) return validation;
  return {
    feedback: reason || "Validation failed",
    severity: "error",
    conflicting_prior_ids: conflictingPriorIds || [],
  };
}

function getDraftFolderPath(draft: DraftFolder): string {
  return joinFolderPath(draft.parentPath, draft.name);
}

function bucketDrafts(drafts: Record<string, DraftItem>) {
  const folders: Record<string, DraftFolder[]> = {};
  const priors: Record<string, DraftPrior[]> = {};

  Object.values(drafts).forEach((draft) => {
    if (draft.kind === "folder") {
      const bucket = folders[draft.parentPath] ?? [];
      bucket.push(draft);
      folders[draft.parentPath] = bucket;
      return;
    }

    const bucket = priors[draft.path] ?? [];
    bucket.push(draft);
    priors[draft.path] = bucket;
  });

  for (const key of Object.keys(folders)) {
    folders[key] = sortByName(folders[key]);
  }
  for (const key of Object.keys(priors)) {
    priors[key] = sortByName(priors[key]);
  }

  return { folders, priors };
}

function buildVisibleRows(
  folderMap: FolderMap,
  expanded: Set<string>,
  drafts: ReturnType<typeof bucketDrafts>,
  path = "",
  depth = 0,
): ExplorerRow[] {
  const normalizedPath = normalizeFolderPath(path);
  const folderData = folderMap[normalizedPath];

  const folderRows = sortByName([
    ...(folderData?.folders ?? []).map((folder) => ({
      key: folderRowKey(folder.path),
      kind: "folder" as const,
      name: getFolderName(folder.path),
      depth,
      path: normalizeFolderPath(folder.path),
      parentPath: normalizedPath,
      isDraft: false,
      expanded: expanded.has(normalizeFolderPath(folder.path)),
    })),
    ...(drafts.folders[normalizedPath] ?? []).map((draft) => ({
      key: draft.key,
      kind: "folder" as const,
      name: draft.name,
      depth,
      path: getDraftFolderPath(draft),
      parentPath: draft.parentPath,
      isDraft: true,
      expanded: false,
      draft,
    })),
  ]);

  const priorRows = sortByName([
    ...(folderData?.priors ?? []).map((prior) => ({
      key: priorRowKey(prior.id),
      kind: "prior" as const,
      name: prior.name,
      depth,
      path: normalizedPath,
      parentPath: normalizedPath,
      isDraft: false,
      prior,
    })),
    ...(drafts.priors[normalizedPath] ?? []).map((draft) => ({
      key: draft.key,
      kind: "prior" as const,
      name: draft.name,
      depth,
      path: draft.path,
      parentPath: draft.path,
      isDraft: true,
      draft,
    })),
  ]);

  const rows: ExplorerRow[] = [];
  folderRows.forEach((row) => {
    rows.push(row);
    if (!row.isDraft && row.expanded) {
      rows.push(...buildVisibleRows(folderMap, expanded, drafts, row.path, depth + 1));
    }
  });
  rows.push(...priorRows);
  return rows;
}

function buildUniqueDraftPriorName(
  parentPath: string,
  folderMap: FolderMap,
  drafts: ReturnType<typeof bucketDrafts>,
): string {
  const taken = new Set<string>();
  folderMap[parentPath]?.priors.forEach((prior) => taken.add(priorStem(prior.name).toLowerCase()));
  (drafts.priors[parentPath] ?? []).forEach((draft) => taken.add(priorStem(draft.name).toLowerCase()));

  let candidate = "untitled";
  let suffix = 2;
  while (taken.has(candidate.toLowerCase())) {
    candidate = `untitled ${suffix}`;
    suffix += 1;
  }
  return candidate;
}

function buildUniqueDraftFolderName(
  parentPath: string,
  folderMap: FolderMap,
  drafts: ReturnType<typeof bucketDrafts>,
): string {
  const taken = new Set<string>();
  folderMap[parentPath]?.folders.forEach((folder) => taken.add(getFolderName(folder.path).toLowerCase()));
  (drafts.folders[parentPath] ?? []).forEach((draft) => taken.add(draft.name.toLowerCase()));

  let candidate = "untitled folder";
  let suffix = 2;
  while (taken.has(candidate.toLowerCase())) {
    candidate = `untitled folder ${suffix}`;
    suffix += 1;
  }
  return candidate;
}

function toEditorPrior(row: ExplorerRow): EditorPrior | null {
  if (row.kind !== "prior") return null;
  if (!row.isDraft || row.draft?.kind !== "prior") return null;
  return {
    id: row.key,
    name: row.draft.name,
    summary: "",
    content: row.draft.content,
    path: row.draft.path,
    prior_status: "draft",
    draftKey: row.key,
  };
}

function isDraftPriorRecord(prior: PriorRecord | null | undefined): boolean {
  return prior?.prior_status === "draft";
}

function toPriorItemRef(row: ExplorerRow): PriorItemRef | null {
  if (row.isDraft) return null;
  if (row.kind === "folder") {
    return { kind: "folder", path: row.path };
  }
  if (!row.prior) return null;
  return { kind: "prior", id: row.prior.id };
}

function itemKeysFromMutation(items: Array<{ kind: "prior" | "folder"; id?: string; path?: string }> | undefined): Set<string> {
  const keys = new Set<string>();
  (items ?? []).forEach((item) => {
    if (item.kind === "folder" && item.path) {
      keys.add(folderRowKey(item.path));
    }
    if (item.kind === "prior" && item.id) {
      keys.add(priorRowKey(item.id));
    }
  });
  return keys;
}

function isDescendantPath(childPath: string, parentPath: string): boolean {
  const child = normalizeFolderPath(childPath);
  const parent = normalizeFolderPath(parentPath);
  return Boolean(parent) && child.startsWith(parent);
}

function SystemToast({
  toast,
  onClose,
}: {
  toast: SystemToastState;
  onClose: () => void;
}) {
  return (
    <div className="priors-system-toast">
      <div className="priors-system-toast-copy">{toast.message}</div>
      <button type="button" className="priors-system-toast-close" onClick={onClose} aria-label="Dismiss notice">
        <X size={16} />
      </button>
    </div>
  );
}

function ReviewPanel({
  review,
  loading,
  saved,
  visible,
  onClose,
}: {
  review: PriorValidationDetail | null;
  loading: boolean;
  saved: boolean;
  visible: boolean;
  onClose: () => void;
}) {
  const tone = review?.severity ?? "info";
  const badgeLabel = loading
    ? "Reviewing prior"
    : tone === "error"
      ? "Needs changes"
      : tone === "warning"
        ? "Needs attention"
        : "Approved";

  return (
    <div className={`split-editor-review-pane${visible ? " visible" : ""}`}>
      <div className="split-editor-review-header">
        <div className="split-editor-review-meta">
          <div className="split-editor-review-badges">
            <span className={`split-editor-review-badge tone-${tone}`}>
              {loading ? <Loader2 size={14} className="spin" /> : tone === "info" ? <Check size={14} /> : <ShieldAlert size={14} />}
              {badgeLabel}
            </span>
            {!loading && saved && (
              <span className="split-editor-review-badge split-editor-review-badge-saved">
                <Check size={14} />
                Saved
              </span>
            )}
            {!loading && review && !saved && (
              <span className="split-editor-review-badge split-editor-review-badge-unsaved">
                <X size={14} />
                Not Saved
              </span>
            )}
          </div>
          <span className="split-editor-review-subtitle">
            {loading ? "Running the prior review now." : "Feedback from the latest save."}
          </span>
        </div>
        <button type="button" className="split-editor-review-close" onClick={onClose} aria-label="Close review panel">
          <X size={16} />
        </button>
      </div>

      {loading ? (
        <div className="split-editor-review-loading">
          <Loader2 size={22} className="spin" />
          <div>
            <div className="split-editor-review-loading-title">Reviewing prior…</div>
            <div className="split-editor-review-loading-copy">
              Validation feedback will appear here as soon as the save finishes.
            </div>
          </div>
        </div>
      ) : review ? (
        <div className="split-editor-review-body">
          <RenderedMarkdown markdown={review.feedback} />
          {review.conflicting_prior_ids.length > 0 && (
            <div className="split-editor-review-conflicts">
              Conflicts: {review.conflicting_prior_ids.join(", ")}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function RenameInput({
  initialName,
  onSubmit,
  onCancel,
  selectStem = false,
}: {
  initialName: string;
  onSubmit: (name: string) => void;
  onCancel: () => void;
  selectStem?: boolean;
}) {
  const [value, setValue] = useState(initialName);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    input.focus();
    if (selectStem && initialName.toLowerCase().endsWith(".md")) {
      input.setSelectionRange(0, initialName.length - 3);
      return;
    }
    input.select();
  }, [initialName, selectStem]);

  return (
    <input
      ref={inputRef}
      className="priors-rename-input"
      value={value}
      onChange={(event) => setValue(event.target.value)}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Enter") {
          const next = value.trim();
          if (next) onSubmit(next);
          else onCancel();
        }
        if (event.key === "Escape") onCancel();
      }}
      onBlur={() => {
        const next = value.trim();
        if (next) onSubmit(next);
        else onCancel();
      }}
      autoFocus
    />
  );
}

function ContextMenu({
  state,
  actions,
  onClose,
}: {
  state: ContextMenuState;
  actions: ContextMenuAction[];
  onClose: () => void;
}) {
  useEffect(() => {
    const handleWindowClick = () => onClose();
    window.addEventListener("click", handleWindowClick);
    return () => window.removeEventListener("click", handleWindowClick);
  }, [onClose]);

  return (
    <div
      className="priors-context-menu"
      style={{ top: state.y, left: state.x }}
      onClick={(event) => event.stopPropagation()}
    >
      {actions.map((action) => (
        <button
          key={action.label}
          type="button"
          className={action.danger ? "ctx-danger" : undefined}
          disabled={action.disabled}
          onClick={() => {
            action.onSelect();
            onClose();
          }}
        >
          <action.icon size={14} /> {action.label}
        </button>
      ))}
    </div>
  );
}

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
      <div className="priors-dialog" onClick={(event) => event.stopPropagation()}>
        <p>{message}</p>
        <div className="priors-dialog-actions">
          <button type="button" className="priors-dialog-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="priors-dialog-confirm" onClick={onConfirm}>
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

function MoveDialog({
  destinationPath,
  rows,
  disabledPaths,
  onSelectDestination,
  onToggleFolder,
  onConfirm,
  onCancel,
}: {
  destinationPath: string;
  rows: ExplorerRow[];
  disabledPaths: Set<string>;
  onSelectDestination: (path: string) => void;
  onToggleFolder: (row: ExplorerRow) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal modal-wide priors-move-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">Choose A Destination Folder</h2>
          <button type="button" className="modal-close" onClick={onCancel} aria-label="Close move dialog">
            <X size={16} />
          </button>
        </div>
        <div className="priors-move-tree">
          {rows.map((row) => {
            const isFolder = row.kind === "folder";
            const normalizedPath = normalizeFolderPath(row.path);
            const disabled = !isFolder || disabledPaths.has(normalizedPath);
            return (
              <ExplorerRowView
                key={`move-${row.key}`}
                row={row}
                selected={isFolder && destinationPath === normalizedPath}
                focused={false}
                renaming={false}
                loading={false}
                disabled={disabled}
                draggable={false}
                showChevron={isFolder && row.path !== ""}
                rowRef={() => {}}
                dragOver={false}
                onSelect={(_event, selectedRow) => {
                  if (selectedRow.kind === "folder") {
                    onSelectDestination(normalizeFolderPath(selectedRow.path));
                  }
                }}
                onContextMenu={() => {}}
                onToggle={onToggleFolder}
                onDragStart={() => {}}
                onDragOver={() => {}}
                onDragLeave={() => {}}
                onDrop={() => {}}
                onDragEnd={() => {}}
                onRenameSubmit={() => {}}
                onRenameCancel={() => {}}
              />
            );
          })}
        </div>
        <div className="priors-dialog-actions">
          <button type="button" className="priors-dialog-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="priors-dialog-confirm" onClick={onConfirm}>
            Move
          </button>
        </div>
      </div>
    </div>
  );
}

function PathBar({
  folderPath,
  priorName,
  onNavigate,
}: {
  folderPath: string;
  priorName?: string | null;
  onNavigate: (path: string) => void;
}) {
  const segments = normalizeFolderPath(folderPath).split("/").filter(Boolean);
  const entries = segments.map((segment, index) => ({
    label: segment,
    path: `${segments.slice(0, index + 1).join("/")}/`,
  }));

  return (
    <div className="priors-pathbar">
      {entries.map((entry, index) => (
        <div key={entry.path || "root"} className="pathbar-segment">
          <button type="button" onClick={() => onNavigate(entry.path)}>
            {entry.label}
          </button>
          {index < entries.length - 1 && <span className="pathbar-sep">/</span>}
        </div>
      ))}
      {priorName ? (
        <div className="pathbar-segment">
          {entries.length > 0 && <span className="pathbar-sep">/</span>}
          <span style={{ padding: "2px 4px", fontSize: "11px", color: "var(--color-text)" }}>
            {displayPriorName(priorName)}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function SplitEditor({
  filename,
  value,
  draftMode,
  onSave,
  onSubmit,
  saving,
  editorAction,
  review,
  reviewLoading,
  reviewSaved,
}: {
  filename: string;
  value: string;
  draftMode: boolean;
  onSave: (value: string) => void;
  onSubmit?: (value: string) => void;
  saving: boolean;
  editorAction: "save" | "save-draft" | "submit" | null;
  review: PriorValidationDetail | null;
  reviewLoading: boolean;
  reviewSaved: boolean;
}) {
  const [mode, setMode] = useState<"edit" | "split" | "preview">("split");
  const [sidePanel, setSidePanel] = useState<"preview" | "review">("preview");
  const [draft, setDraft] = useState(value);
  const modeBeforeReviewRef = useRef<"edit" | "split" | "preview">("split");
  const reviewTriggerRef = useRef<null | "save" | "submit">(null);
  const dirty = draft !== value;
  const reviewAvailable = reviewLoading || Boolean(review);
  const canSubmitDraft = Boolean(draftMode && onSubmit);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  useEffect(() => {
    const trigger = reviewAvailable && (editorAction === "save" || editorAction === "submit")
      ? editorAction
      : null;
    if (trigger && reviewTriggerRef.current !== trigger) {
      modeBeforeReviewRef.current = mode;
      setMode("split");
      setSidePanel("review");
      reviewTriggerRef.current = trigger;
      return;
    }
    if (editorAction === null) {
      reviewTriggerRef.current = null;
    }
  }, [editorAction, mode, reviewAvailable]);

  const closeReviewPanel = useCallback(() => {
    setSidePanel("preview");
    setMode(modeBeforeReviewRef.current);
  }, []);

  return (
    <div className="split-editor">
      <div className="split-editor-toolbar">
        <div className="split-editor-tabs">
          <button type="button" className={mode === "edit" ? "active" : ""} onClick={() => setMode("edit")}>
            <PenLine size={14} /> Edit
          </button>
          <button type="button" className={mode === "split" ? "active" : ""} onClick={() => setMode("split")}>
            <FileText size={14} /> Split
          </button>
          <button
            type="button"
            className={mode === "preview" ? "active" : ""}
            onClick={() => setMode("preview")}
          >
            <Eye size={14} /> Preview
          </button>
          {reviewAvailable && (
            <button
              type="button"
              className={`split-editor-review-tab ${sidePanel === "review" && mode === "split" ? "active" : ""} tone-${review?.severity ?? "info"}`}
              onClick={() => {
                setMode("split");
                setSidePanel("review");
              }}
            >
              {reviewLoading ? <Loader2 size={14} className="spin" /> : review?.severity === "info" ? <Check size={14} /> : <ShieldAlert size={14} />}
              Review
            </button>
          )}
        </div>
        <span className="split-editor-filename">
          {filename}
          {draftMode && <span className="split-editor-draft-pill">Draft</span>}
          {dirty && <span className="split-editor-dirty-dot" />}
          {saving && (
            <span className="split-editor-status-chip">
              {editorAction === "submit" ? "Submitting…" : editorAction === "save-draft" ? "Saving draft…" : "Saving…"}
            </span>
          )}
        </span>
        {(dirty || canSubmitDraft) && (
          <div className="split-editor-actions">
            {dirty && (
              <button
                type="button"
                className="split-editor-discard"
                onClick={() => setDraft(value)}
                title="Discard changes"
                disabled={saving}
              >
                <X size={14} />
              </button>
            )}
            {draftMode ? (
              <>
                {dirty && (
                  <button
                    type="button"
                    className={`split-editor-save draft-save${saving && editorAction === "save-draft" ? " saving" : ""}`}
                    onClick={() => onSave(draft)}
                    title="Save Draft"
                    disabled={saving}
                  >
                    {saving && editorAction === "save-draft" ? <Loader2 size={14} className="spin" /> : <Check size={14} />}
                    <span>{saving && editorAction === "save-draft" ? "Saving Draft…" : "Save Draft"}</span>
                  </button>
                )}
                {onSubmit && (
                  <button
                    type="button"
                    className={`split-editor-save submit${saving && editorAction === "submit" ? " saving" : ""}`}
                    onClick={() => onSubmit(draft)}
                    title="Submit"
                    disabled={saving}
                  >
                    {saving && editorAction === "submit" ? <Loader2 size={14} className="spin" /> : <Check size={14} />}
                    <span>{saving && editorAction === "submit" ? "Submitting…" : "Submit"}</span>
                  </button>
                )}
              </>
            ) : (
              <button
                type="button"
                className={`split-editor-save${saving ? " saving" : ""}`}
                onClick={() => onSave(draft)}
                title="Save"
                disabled={saving}
              >
                {saving ? <Loader2 size={14} className="spin" /> : <Check size={14} />}
                <span>{saving ? "Saving…" : "Save"}</span>
              </button>
            )}
          </div>
        )}
      </div>
      <div className={`split-editor-body mode-${mode}`}>
        {mode !== "preview" && (
          <textarea
            className="split-editor-textarea"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            spellCheck={false}
          />
        )}
        {mode !== "edit" && (
          <div className="split-editor-sidepanel">
            <div className={`split-editor-preview-panel${sidePanel === "review" && mode === "split" ? " review-underlay" : ""}`}>
              <div className="split-editor-preview">
                <RenderedMarkdown markdown={draft} />
              </div>
            </div>
            <ReviewPanel
              review={review}
              loading={reviewLoading}
              saved={reviewSaved}
              visible={sidePanel === "review" && mode === "split" && reviewAvailable}
              onClose={closeReviewPanel}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function ExplorerRowView({
  row,
  selected,
  focused,
  renaming,
  loading,
  onSelect,
  onContextMenu,
  onToggle,
  onRenameSubmit,
  onRenameCancel,
  rowRef,
  dragOver,
  draggable,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDrop,
  onDragEnd,
  showChevron = row.kind === "folder",
  disabled = false,
}: {
  row: ExplorerRow;
  selected: boolean;
  focused: boolean;
  renaming: boolean;
  loading: boolean;
  onSelect: (event: ReactMouseEvent<HTMLDivElement>, row: ExplorerRow) => void;
  onContextMenu: (event: ReactMouseEvent<HTMLDivElement>, row: ExplorerRow) => void;
  onToggle: (row: ExplorerRow) => void;
  onRenameSubmit: (row: ExplorerRow, name: string) => void;
  onRenameCancel: () => void;
  rowRef: (node: HTMLDivElement | null) => void;
  dragOver: boolean;
  draggable: boolean;
  onDragStart: (event: React.DragEvent<HTMLDivElement>, row: ExplorerRow) => void;
  onDragOver: (event: React.DragEvent<HTMLDivElement>, row: ExplorerRow) => void;
  onDragLeave: (event: React.DragEvent<HTMLDivElement>, row: ExplorerRow) => void;
  onDrop: (event: React.DragEvent<HTMLDivElement>, row: ExplorerRow) => void;
  onDragEnd: () => void;
  showChevron?: boolean;
  disabled?: boolean;
}) {
  const label = row.kind === "folder" ? row.name : displayPriorName(row.name);
  const draftPrior = row.kind === "prior" && (row.isDraft || row.prior?.prior_status === "draft");
  const icon = row.kind === "folder"
    ? <Folder size={14} className="tree-icon folder-icon" />
    : draftPrior
      ? <PenLine size={14} className="tree-icon file-icon draft-file-icon" />
      : <FileText size={14} className="tree-icon file-icon" />;

  return (
    <div
      ref={rowRef}
      data-row-key={row.key}
      className={`tree-node${selected ? " selected" : ""}${selected && !focused ? " multi-selected" : ""}${focused ? " focused" : ""}${dragOver ? " drag-over" : ""}${disabled ? " disabled" : ""}`}
      style={{ paddingLeft: `${row.depth * 16 + 8}px` }}
      draggable={draggable && !disabled}
      onClick={(event) => {
        if (disabled) return;
        onSelect(event, row);
      }}
      onDoubleClick={() => {
        if (!disabled && row.kind === "folder") onToggle(row);
      }}
      onContextMenu={(event) => {
        if (disabled) return;
        onContextMenu(event, row);
      }}
      onDragStart={(event) => {
        if (disabled) return;
        onDragStart(event, row);
      }}
      onDragOver={(event) => {
        if (disabled) return;
        onDragOver(event, row);
      }}
      onDragLeave={(event) => {
        if (disabled) return;
        onDragLeave(event, row);
      }}
      onDrop={(event) => {
        if (disabled) return;
        onDrop(event, row);
      }}
      onDragEnd={() => {
        if (disabled) return;
        onDragEnd();
      }}
    >
      <button
        type="button"
        className={`tree-chevron${showChevron ? "" : " invisible"}`}
        onClick={(event) => {
          event.stopPropagation();
          if (!disabled && row.kind === "folder") onToggle(row);
        }}
        tabIndex={-1}
        aria-label={row.kind === "folder" ? (row.expanded ? "Collapse folder" : "Expand folder") : "No children"}
        disabled={!showChevron}
      >
        {showChevron ? <ChevronRight size={14} className={row.expanded ? "rotated" : ""} /> : <ChevronRight size={14} />}
      </button>
      {icon}
      {renaming ? (
        <RenameInput
          initialName={label}
          selectStem={row.kind === "prior"}
          onSubmit={(name) => onRenameSubmit(row, name)}
          onCancel={onRenameCancel}
        />
      ) : (
        <>
          <span className="tree-label">{label}</span>
          {draftPrior && <span className="tree-row-pill">Draft</span>}
        </>
      )}
      {loading && <Loader2 size={12} className="spin tree-row-loader" />}
    </div>
  );
}

export function PriorsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const treeRef = useRef<HTMLDivElement | null>(null);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const dragExpandTimerRef = useRef<number | null>(null);
  const dragCancelledRef = useRef(false);

  const [projectName, setProjectName] = useState("Project");
  const [folderMap, setFolderMap] = useState<FolderMap>({});
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([""]));
  const [drafts, setDrafts] = useState<Record<string, DraftItem>>({});
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [focusedKey, setFocusedKey] = useState<string | null>(null);
  const [anchorKey, setAnchorKey] = useState<string | null>(null);
  const [selectedPrior, setSelectedPrior] = useState<EditorPrior | null>(null);
  const [selectedPriorLoading, setSelectedPriorLoading] = useState(false);
  const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [editorAction, setEditorAction] = useState<null | "save" | "save-draft" | "submit">(null);
  const [reviewResult, setReviewResult] = useState<PriorValidationDetail | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewSaved, setReviewSaved] = useState(false);
  const [systemToast, setSystemToast] = useState<SystemToastState | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [renamingKey, setRenamingKey] = useState<string | null>(null);
  const [deleteDialog, setDeleteDialog] = useState<DeleteDialogState | null>(null);
  const [moveDialog, setMoveDialog] = useState<MoveDialogState | null>(null);
  const [clipboard, setClipboard] = useState<{ items: PriorItemRef[] } | null>(null);
  const [draggedKeys, setDraggedKeys] = useState<Set<string>>(new Set());
  const [dragOverPath, setDragOverPath] = useState<string | null>(null);
  const expandedRef = useRef(expanded);

  const showSystemToast = useCallback((message: string) => {
    setSystemToast({ id: Date.now(), message });
  }, []);

  useEffect(() => {
    expandedRef.current = expanded;
  }, [expanded]);

  useEffect(() => {
    if (!systemToast) return;
    const timer = window.setTimeout(() => {
      setSystemToast((current) => (current?.id === systemToast.id ? null : current));
    }, 10000);
    return () => window.clearTimeout(timer);
  }, [systemToast]);

  useEffect(() => {
    if (!projectId) return;
    fetchProject(projectId)
      .then((project) => setProjectName(project.name))
      .catch(() => setProjectName("Project"));
  }, [projectId]);

  const draftBuckets = useMemo(() => bucketDrafts(drafts), [drafts]);
  const visibleRows = useMemo(
    () => buildVisibleRows(folderMap, expanded, draftBuckets),
    [draftBuckets, expanded, folderMap],
  );
  const rowsByKey = useMemo(
    () => new Map(visibleRows.map((row) => [row.key, row])),
    [visibleRows],
  );
  const selectedRows = useMemo(
    () => visibleRows.filter((row) => selectedKeys.has(row.key)),
    [selectedKeys, visibleRows],
  );
  const primaryRow = useMemo(() => {
    if (focusedKey && selectedKeys.has(focusedKey)) {
      return rowsByKey.get(focusedKey) ?? null;
    }
    return selectedRows[selectedRows.length - 1] ?? null;
  }, [focusedKey, rowsByKey, selectedKeys, selectedRows]);
  const singleSelectedRow = selectedRows.length === 1 ? primaryRow : null;

  const currentActionFolderPath = primaryRow ? primaryRow.path : "";
  const currentBarFolderPath = singleSelectedRow ? singleSelectedRow.path : "";
  const currentBarPriorName = singleSelectedRow?.kind === "prior" ? singleSelectedRow.name : null;
  const explorerLoading = loadingPaths.has("");

  const setSingleSelection = useCallback((key: string | null) => {
    if (!key) {
      setSelectedKeys(new Set());
      setFocusedKey(null);
      setAnchorKey(null);
      return;
    }
    setSelectedKeys(new Set([key]));
    setFocusedKey(key);
    setAnchorKey(key);
  }, []);

  const fetchFolder = useCallback(async (path: string): Promise<FolderLsResponse | undefined> => {
    if (!projectId) return;
    const normalized = normalizeFolderPath(path);
    setLoadingPaths((prev) => new Set(prev).add(normalized));
    try {
      const result = await fetchPriorsFolder(projectId, normalized);
      setFolderMap((prev) => ({ ...prev, [normalized]: result }));
      return result;
    } catch (fetchError) {
      const message = normalizeError(fetchError);
      if (isConnectivityError(message)) {
        showSystemToast("Unable to reach the priors backend through so-server.");
      } else {
        showSystemToast(message);
      }
      return undefined;
    } finally {
      setLoadingPaths((prev) => {
        const next = new Set(prev);
        next.delete(normalized);
        return next;
      });
    }
  }, [projectId, showSystemToast]);

  const reloadExpandedFolders = useCallback(async (override?: Set<string>) => {
    const paths = new Set(override ?? expandedRef.current);
    paths.add("");
    setFolderMap({});
    await Promise.all([...paths].map((path) => fetchFolder(path)));
  }, [fetchFolder]);

  const ensureFolderExpanded = useCallback((path: string) => {
    const normalized = normalizeFolderPath(path);
    setExpanded((prev) => {
      if (prev.has(normalized)) return prev;
      const next = new Set(prev).add(normalized);
      expandedRef.current = next;
      return next;
    });
    if (!folderMap[normalized]) {
      void fetchFolder(normalized);
    }
  }, [fetchFolder, folderMap]);

  useEffect(() => {
    setFolderMap({});
    setExpanded(new Set([""]));
    expandedRef.current = new Set([""]);
    setDrafts({});
    setSelectedKeys(new Set());
    setFocusedKey(null);
    setAnchorKey(null);
    setSelectedPrior(null);
    setSelectedPriorLoading(false);
    setEditorAction(null);
    setReviewResult(null);
    setReviewLoading(false);
    setReviewSaved(false);
    setSystemToast(null);
    setContextMenu(null);
    setRenamingKey(null);
    setDeleteDialog(null);
    setMoveDialog(null);
    if (projectId) {
      void fetchFolder("");
    }
  }, [fetchFolder, projectId]);

  useEffect(() => subscribe("priors_refresh", () => {
    void reloadExpandedFolders();
  }), [reloadExpandedFolders]);

  useEffect(() => () => {
    if (dragExpandTimerRef.current !== null) {
      window.clearTimeout(dragExpandTimerRef.current);
    }
  }, []);

  useEffect(() => {
    setSelectedKeys((prev) => {
      const next = new Set([...prev].filter((key) => rowsByKey.has(key)));
      if (next.size === prev.size) return prev;
      return next;
    });
    if (focusedKey && !rowsByKey.has(focusedKey)) {
      setFocusedKey(null);
    }
    if (anchorKey && !rowsByKey.has(anchorKey)) {
      setAnchorKey(null);
    }
    if (renamingKey && !rowsByKey.has(renamingKey)) {
      setRenamingKey(null);
    }
  }, [anchorKey, focusedKey, renamingKey, rowsByKey]);

  useEffect(() => {
    if (!focusedKey) return;
    const node = rowRefs.current[focusedKey];
    node?.scrollIntoView({ block: "nearest" });
  }, [focusedKey]);

  const handleMutationError = useCallback((mutationError: unknown) => {
    const message = normalizeError(mutationError);
    setSaving(false);
    setEditorAction(null);
    setReviewLoading(false);
    if (isConnectivityError(message)) {
      showSystemToast("Unable to reach the priors backend through so-server.");
      return;
    }
    showSystemToast(message);
  }, [showSystemToast]);

  const acceptMutation = useCallback((
    result: {
      status: string;
      validation?: PriorValidationDetail;
      reason?: string;
      conflicting_prior_ids?: string[];
    },
    feedbackSurface: "toast" | "review" = "toast",
  ) => {
    const review = result.status === "rejected"
      ? buildValidationResult(result.validation, result.reason, result.conflicting_prior_ids)
      : (result.validation ?? null);

    if (feedbackSurface === "review") {
      setReviewResult(review);
      setReviewLoading(false);
      setReviewSaved(result.status !== "rejected");
    }

    if (result.status === "rejected") {
      if (feedbackSurface === "toast" && review?.feedback) {
        showSystemToast(review.feedback);
      }
      return false;
    }
    return true;
  }, [showSystemToast]);

  useEffect(() => {
    setEditorAction(null);
    setReviewResult(null);
    setReviewLoading(false);
    setReviewSaved(false);

    if (!singleSelectedRow) {
      setSelectedPrior(null);
      setSelectedPriorLoading(false);
      return;
    }

    if (singleSelectedRow.kind === "folder") {
      setSelectedPrior(null);
      setSelectedPriorLoading(false);
      return;
    }

    if (singleSelectedRow.isDraft) {
      setSelectedPrior(toEditorPrior(singleSelectedRow));
      setSelectedPriorLoading(false);
      return;
    }

    if (!projectId || !singleSelectedRow.prior) {
      setSelectedPrior(null);
      setSelectedPriorLoading(false);
      return;
    }

    let cancelled = false;
    setSelectedPriorLoading(true);
    fetchPrior(projectId, singleSelectedRow.prior.id)
      .then((fresh) => {
        if (!cancelled) {
          setSelectedPrior(fresh);
          setSelectedPriorLoading(false);
        }
      })
      .catch((fetchError) => {
        if (!cancelled) {
          setSelectedPriorLoading(false);
          handleMutationError(fetchError);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [handleMutationError, projectId, singleSelectedRow]);

  const setRangeSelection = useCallback((targetKey: string) => {
    const baseKey = anchorKey ?? focusedKey ?? targetKey;
    const startIndex = visibleRows.findIndex((row) => row.key === baseKey);
    const endIndex = visibleRows.findIndex((row) => row.key === targetKey);
    if (startIndex === -1 || endIndex === -1) {
      setSingleSelection(targetKey);
      return;
    }
    const [start, end] = startIndex < endIndex ? [startIndex, endIndex] : [endIndex, startIndex];
    const nextKeys = new Set(visibleRows.slice(start, end + 1).map((row) => row.key));
    setSelectedKeys(nextKeys);
    setFocusedKey(targetKey);
    setAnchorKey(baseKey);
  }, [anchorKey, focusedKey, setSingleSelection, visibleRows]);

  const toggleSelection = useCallback((key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    setFocusedKey(key);
    setAnchorKey(key);
  }, []);

  const handleRowClick = useCallback((event: React.MouseEvent<HTMLDivElement>, row: ExplorerRow) => {
    treeRef.current?.focus();
    setContextMenu(null);
    if (event.shiftKey) {
      setRangeSelection(row.key);
      return;
    }
    if (event.metaKey || event.ctrlKey) {
      toggleSelection(row.key);
      return;
    }
    setSingleSelection(row.key);
  }, [setRangeSelection, setSingleSelection, toggleSelection]);

  const handleToggleFolder = useCallback((row: ExplorerRow) => {
    if (row.kind !== "folder" || row.isDraft) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(row.path)) next.delete(row.path);
      else next.add(row.path);
      expandedRef.current = next;
      return next;
    });
    if (!folderMap[row.path]) {
      void fetchFolder(row.path);
    }
  }, [fetchFolder, folderMap]);

  const clearDrafts = useCallback((keys: string[]) => {
    if (keys.length === 0) return;
    setDrafts((prev) => {
      const next = { ...prev };
      keys.forEach((key) => {
        delete next[key];
      });
      return next;
    });
  }, []);

  const handleCreateDraftPrior = useCallback(async (parentPath: string) => {
    if (!projectId) return;
    const normalizedParent = normalizeFolderPath(parentPath);
    setExpanded((prev) => {
      if (prev.has(normalizedParent)) return prev;
      const next = new Set(prev).add(normalizedParent);
      expandedRef.current = next;
      return next;
    });
    let resolvedFolderMap = folderMap;
    if (!folderMap[normalizedParent]) {
      const loaded = await fetchFolder(normalizedParent);
      if (!loaded) return;
      resolvedFolderMap = { ...folderMap, [normalizedParent]: loaded };
    }
    const name = buildUniqueDraftPriorName(normalizedParent, resolvedFolderMap, draftBuckets);
    setSaving(true);
    try {
      const result = await createDraftPrior(projectId, {
        name,
        content: seedMarkdown(name),
        path: normalizedParent,
      });
      const nextExpanded = new Set(expandedRef.current);
      nextExpanded.add(normalizedParent);
      nextExpanded.add("");
      setExpanded(nextExpanded);
      expandedRef.current = nextExpanded;
      await reloadExpandedFolders(nextExpanded);
      const nextKey = priorRowKey(result.id);
      setSingleSelection(nextKey);
      setRenamingKey(nextKey);
    } catch (mutationError) {
      handleMutationError(mutationError);
    } finally {
      setSaving(false);
      setEditorAction(null);
    }
  }, [draftBuckets, fetchFolder, folderMap, handleMutationError, projectId, reloadExpandedFolders, setSingleSelection]);

  const handleCreateDraftFolder = useCallback(async (parentPath: string) => {
    const normalizedParent = normalizeFolderPath(parentPath);
    setExpanded((prev) => {
      if (prev.has(normalizedParent)) return prev;
      const next = new Set(prev).add(normalizedParent);
      expandedRef.current = next;
      return next;
    });
    let resolvedFolderMap = folderMap;
    if (!folderMap[normalizedParent]) {
      const loaded = await fetchFolder(normalizedParent);
      if (!loaded) return;
      resolvedFolderMap = { ...folderMap, [normalizedParent]: loaded };
    }
    const key = createDraftKey("draft-folder");
    const draft: DraftFolder = {
      key,
      kind: "folder",
      name: buildUniqueDraftFolderName(normalizedParent, resolvedFolderMap, draftBuckets),
      parentPath: normalizedParent,
    };
    setDrafts((prev) => ({ ...prev, [key]: draft }));
    setRenamingKey(key);
    setSingleSelection(key);
  }, [draftBuckets, fetchFolder, folderMap, setSingleSelection]);

  const handleRenameSubmit = useCallback(async (row: ExplorerRow, nextName: string) => {
    if (!projectId) return;
    const trimmed = nextName.trim();
    if (!trimmed) {
      setRenamingKey(null);
      return;
    }

    setSaving(true);
    try {
      if (row.isDraft && row.draft?.kind === "prior") {
        const nextStem = priorStem(trimmed);
        if (!nextStem) return;
        setDrafts((prev) => ({
          ...prev,
          [row.key]: {
            ...row.draft!,
            name: nextStem,
          },
        }));
        setRenamingKey(null);
        return;
      }

      if (row.isDraft && row.draft?.kind === "folder") {
        const nextPath = joinFolderPath(row.draft.parentPath, trimmed);
        await createPriorFolder(projectId, nextPath);
        clearDrafts([row.key]);
        const nextExpanded = new Set(expandedRef.current);
        nextExpanded.add(row.draft.parentPath);
        nextExpanded.add(nextPath);
        nextExpanded.add("");
        setExpanded(nextExpanded);
        expandedRef.current = nextExpanded;
        await reloadExpandedFolders(nextExpanded);
        setSingleSelection(folderRowKey(nextPath));
        setRenamingKey(null);
        return;
      }

      if (row.kind === "folder") {
        const newPath = joinFolderPath(getParentFolderPath(row.path), trimmed);
        await movePriorFolder(projectId, row.path, newPath);
        const nextExpanded = new Set(
          [...expandedRef.current].map((path) => (path === row.path || path.startsWith(row.path)
            ? `${newPath}${path.slice(row.path.length)}`
            : path)),
        );
        nextExpanded.add("");
        setExpanded(nextExpanded);
        expandedRef.current = nextExpanded;
        await reloadExpandedFolders(nextExpanded);
        setSingleSelection(folderRowKey(newPath));
        setRenamingKey(null);
        return;
      }

      if (!row.prior) return;
      const result = await updatePrior(projectId, row.prior.id, { name: priorStem(trimmed) });
      if (!acceptMutation(result)) return;
      await reloadExpandedFolders();
      setSingleSelection(priorRowKey(row.prior.id));
      setRenamingKey(null);
    } catch (mutationError) {
      handleMutationError(mutationError);
    } finally {
      setSaving(false);
    }
  }, [acceptMutation, clearDrafts, handleMutationError, projectId, reloadExpandedFolders, setSingleSelection]);

  const handleCopyRows = useCallback((rows: ExplorerRow[]) => {
    const items = rows
      .map(toPriorItemRef)
      .filter((item): item is PriorItemRef => Boolean(item));
    if (items.length === 0) return;
    setClipboard({ items });
  }, []);

  const handlePasteItems = useCallback(async (destinationPath: string) => {
    if (!projectId || !clipboard?.items.length) return;
    setSaving(true);
    try {
      const normalizedDestination = normalizeFolderPath(destinationPath);
      const result = await copyPriorItems(projectId, clipboard.items, normalizedDestination, true);
      const nextExpanded = new Set(expandedRef.current);
      nextExpanded.add(normalizedDestination);
      nextExpanded.add("");
      setExpanded(nextExpanded);
      expandedRef.current = nextExpanded;
      await reloadExpandedFolders(nextExpanded);
      const nextKeys = itemKeysFromMutation(result.items);
      if (nextKeys.size > 0) {
        const [firstKey] = nextKeys;
        setSelectedKeys(nextKeys);
        setFocusedKey(firstKey ?? null);
        setAnchorKey(firstKey ?? null);
      }
    } catch (mutationError) {
      handleMutationError(mutationError);
    } finally {
      setSaving(false);
    }
  }, [clipboard, handleMutationError, projectId, reloadExpandedFolders]);

  const handleDeleteSelection = useCallback(async (keys: string[]) => {
    if (!projectId || keys.length === 0) return;
    const rows = keys.map((key) => rowsByKey.get(key)).filter((row): row is ExplorerRow => Boolean(row));
    if (rows.length === 0) return;

    setSaving(true);
    try {
      const draftKeys = rows.filter((row) => row.isDraft).map((row) => row.key);
      const persistedItems = rows
        .map(toPriorItemRef)
        .filter((item): item is PriorItemRef => Boolean(item));

      if (draftKeys.length > 0) {
        clearDrafts(draftKeys);
      }
      if (persistedItems.length > 0) {
        await deletePriorItems(projectId, persistedItems);
      }

      const removedFolders = rows
        .filter((row) => row.kind === "folder")
        .map((row) => row.path);
      if (removedFolders.length > 0) {
        const nextExpanded = new Set(
          [...expandedRef.current].filter((path) => path === "" || !removedFolders.some((folderPath) => isDescendantPath(path, folderPath) || path === folderPath)),
        );
        setExpanded(nextExpanded);
        expandedRef.current = nextExpanded;
        await reloadExpandedFolders(nextExpanded);
      } else if (persistedItems.length > 0) {
        await reloadExpandedFolders();
      }

      setSelectedKeys(new Set());
      setFocusedKey(null);
      setAnchorKey(null);
      setDeleteDialog(null);
    } catch (mutationError) {
      handleMutationError(mutationError);
    } finally {
      setSaving(false);
    }
  }, [clearDrafts, handleMutationError, projectId, reloadExpandedFolders, rowsByKey]);

  const handleMoveSelection = useCallback(async (keys: string[], destinationPath: string) => {
    if (!projectId || keys.length === 0) return;
    const rows = keys.map((key) => rowsByKey.get(key)).filter((row): row is ExplorerRow => Boolean(row));
    const items = rows.map(toPriorItemRef).filter((item): item is PriorItemRef => Boolean(item));
    if (items.length === 0) return;

    setSaving(true);
    try {
      const normalizedDestination = normalizeFolderPath(destinationPath);
      const result = await movePriorItems(projectId, items, normalizedDestination);
      const nextExpanded = new Set(expandedRef.current);
      nextExpanded.add(normalizedDestination);
      nextExpanded.add("");
      setExpanded(nextExpanded);
      expandedRef.current = nextExpanded;
      await reloadExpandedFolders(nextExpanded);
      const nextKeys = itemKeysFromMutation(result.items);
      if (nextKeys.size > 0) {
        const [firstKey] = nextKeys;
        setSelectedKeys(nextKeys);
        setFocusedKey(firstKey ?? null);
        setAnchorKey(firstKey ?? null);
      }
      setMoveDialog(null);
      setDraggedKeys(new Set());
      setDragOverPath(null);
    } catch (mutationError) {
      handleMutationError(mutationError);
    } finally {
      setSaving(false);
    }
  }, [handleMutationError, projectId, reloadExpandedFolders, rowsByKey]);

  const clearDragState = useCallback(() => {
    if (dragExpandTimerRef.current !== null) {
      window.clearTimeout(dragExpandTimerRef.current);
      dragExpandTimerRef.current = null;
    }
    setDraggedKeys(new Set());
    setDragOverPath(null);
  }, []);

  useEffect(() => {
    const hasTransientState = Boolean(
      contextMenu
      || moveDialog
      || deleteDialog
      || renamingKey
      || draggedKeys.size > 0
      || dragOverPath,
    );
    if (!hasTransientState) return;

    const handleWindowKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;

      if (draggedKeys.size > 0 || dragOverPath) {
        event.preventDefault();
        dragCancelledRef.current = true;
        clearDragState();
        return;
      }
      if (contextMenu) {
        event.preventDefault();
        setContextMenu(null);
        return;
      }
      if (moveDialog) {
        event.preventDefault();
        setMoveDialog(null);
        return;
      }
      if (deleteDialog) {
        event.preventDefault();
        setDeleteDialog(null);
        return;
      }
      if (renamingKey) {
        event.preventDefault();
        setRenamingKey(null);
      }
    };

    window.addEventListener("keydown", handleWindowKeyDown);
    return () => window.removeEventListener("keydown", handleWindowKeyDown);
  }, [clearDragState, contextMenu, deleteDialog, dragOverPath, draggedKeys.size, moveDialog, renamingKey]);

  const handleSaveContent = useCallback(async (nextContent: string) => {
    if (!projectId || !selectedPrior) return;
    const draftSave = isDraftPriorRecord(selectedPrior);
    setSaving(true);
    setEditorAction(draftSave ? "save-draft" : "save");
    if (draftSave) {
      setReviewLoading(false);
    } else {
      setReviewLoading(true);
      setReviewResult(null);
      setReviewSaved(false);
    }
    try {
      const result = await updatePrior(projectId, selectedPrior.id, { content: nextContent });
      if (!acceptMutation(result, draftSave ? "toast" : "review")) return;
      await reloadExpandedFolders();
      const fresh = await fetchPrior(projectId, selectedPrior.id);
      setSelectedPrior(fresh);
      setSelectedPriorLoading(false);
    } catch (mutationError) {
      handleMutationError(mutationError);
    } finally {
      setSaving(false);
      setEditorAction(null);
    }
  }, [acceptMutation, handleMutationError, projectId, reloadExpandedFolders, selectedPrior]);

  const handleSubmitDraft = useCallback(async (nextContent: string) => {
    if (!projectId || !selectedPrior || !isDraftPriorRecord(selectedPrior)) return;
    setSaving(true);
    setEditorAction("submit");
    setReviewLoading(true);
    setReviewResult(null);
    setReviewSaved(false);
    try {
      const result = await submitPrior(projectId, selectedPrior.id, { content: nextContent });
      if (!acceptMutation(result, "review")) return;
      await reloadExpandedFolders();
      const fresh = await fetchPrior(projectId, selectedPrior.id);
      setSelectedPrior(fresh);
      setSelectedPriorLoading(false);
    } catch (mutationError) {
      handleMutationError(mutationError);
    } finally {
      setSaving(false);
      setEditorAction(null);
    }
  }, [acceptMutation, handleMutationError, projectId, reloadExpandedFolders, selectedPrior]);

  const moveDialogDisabledPaths = useMemo(() => {
    const disabled = new Set<string>();
    if (!moveDialog) return disabled;
    moveDialog.keys.forEach((key) => {
      const row = rowsByKey.get(key);
      if (row?.kind === "folder") {
        disabled.add(row.path);
        visibleRows.forEach((candidate) => {
          if (candidate.kind === "folder" && isDescendantPath(candidate.path, row.path)) {
            disabled.add(candidate.path);
          }
        });
      }
    });
    return disabled;
  }, [moveDialog, rowsByKey, visibleRows]);

  const moveDialogRows = useMemo<ExplorerRow[]>(() => {
    const rootRow: ExplorerRow = {
      key: folderRowKey(""),
      kind: "folder",
      name: "root",
      depth: 0,
      path: "",
      parentPath: "",
      isDraft: false,
      expanded: true,
    };
    return [rootRow, ...visibleRows.filter((row) => !row.isDraft)];
  }, [visibleRows]);

  const contextMenuActions = useMemo(() => {
    if (!contextMenu) return [];
    const menuRows = contextMenu.selectionKeys
      .map((key) => rowsByKey.get(key))
      .filter((row): row is ExplorerRow => Boolean(row));
    const singleRow = menuRows.length === 1 ? menuRows[0] : null;
    const canCopy = menuRows.length > 0 && menuRows.every((row) => !row.isDraft);
    const canMove = canCopy;
    const canRename = Boolean(singleRow);
    const pasteTargetPath = singleRow?.kind === "folder" ? singleRow.path : contextMenu.backgroundPath;
    const canPaste = Boolean(clipboard?.items.length) && menuRows.every((row) => row.kind !== "prior") && !singleRow?.isDraft;
    const actions: ContextMenuAction[] = [];

    if (!singleRow || singleRow.kind === "folder") {
      const targetPath = singleRow?.kind === "folder" ? singleRow.path : contextMenu.backgroundPath;
      actions.push({
        label: "New Prior",
        icon: Plus,
        onSelect: () => {
          void handleCreateDraftPrior(targetPath);
        },
      });
      actions.push({
        label: "New Folder",
        icon: FolderPlus,
        onSelect: () => {
          void handleCreateDraftFolder(targetPath);
        },
      });
      if (canPaste && clipboard) {
        actions.push({
          label: "Paste",
          icon: ClipboardPaste,
          onSelect: () => {
            void handlePasteItems(pasteTargetPath);
          },
        });
      }
    }

    if (menuRows.length > 0) {
      if (canCopy) {
        actions.push({
          label: "Copy",
          icon: Copy,
          onSelect: () => handleCopyRows(menuRows),
        });
      }
      if (canMove) {
        actions.push({
          label: "Move…",
          icon: ArrowRightLeft,
          onSelect: () => setMoveDialog({
            keys: menuRows.map((row) => row.key),
            destinationPath: singleRow?.kind === "folder" ? getParentFolderPath(singleRow.path) : pasteTargetPath,
          }),
        });
      }
      if (canRename) {
        actions.push({
          label: "Rename",
          icon: Pencil,
          onSelect: () => setRenamingKey(singleRow!.key),
        });
      }
      actions.push({
        label: "Delete",
        icon: Trash2,
        danger: true,
        onSelect: () => setDeleteDialog({ keys: menuRows.map((row) => row.key) }),
      });
    }

    return actions;
  }, [clipboard, contextMenu, handleCopyRows, handleCreateDraftFolder, handleCreateDraftPrior, handlePasteItems, rowsByKey]);

  const handleTreeKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (renamingKey) return;
    if (visibleRows.length === 0) return;

    const currentIndex = focusedKey ? visibleRows.findIndex((row) => row.key === focusedKey) : -1;
    const currentRow = currentIndex >= 0 ? visibleRows[currentIndex] : primaryRow;

    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "c") {
      if (selectedRows.length > 0 && selectedRows.every((row) => !row.isDraft)) {
        event.preventDefault();
        handleCopyRows(selectedRows);
      }
      return;
    }

    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "v") {
      if (clipboard?.items.length) {
        event.preventDefault();
        void handlePasteItems(currentActionFolderPath);
      }
      return;
    }

    if (event.key === "Delete" || event.key === "Backspace") {
      if (selectedRows.length > 0) {
        event.preventDefault();
        setDeleteDialog({ keys: selectedRows.map((row) => row.key) });
      }
      return;
    }

    if (event.key === "F2" && selectedRows.length === 1) {
      event.preventDefault();
      setRenamingKey(selectedRows[0].key);
      return;
    }

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const delta = event.key === "ArrowDown" ? 1 : -1;
      const nextIndex = currentIndex === -1
        ? (delta > 0 ? 0 : visibleRows.length - 1)
        : Math.min(Math.max(currentIndex + delta, 0), visibleRows.length - 1);
      const target = visibleRows[nextIndex];
      if (!target) return;
      if (event.shiftKey) {
        setRangeSelection(target.key);
      } else {
        setSingleSelection(target.key);
      }
      return;
    }

    if (event.key === "ArrowRight" && currentRow?.kind === "folder") {
      event.preventDefault();
      if (!currentRow.isDraft && !expanded.has(currentRow.path)) {
        handleToggleFolder(currentRow);
        return;
      }
      const nextRow = visibleRows[currentIndex + 1];
      if (nextRow && nextRow.depth === currentRow.depth + 1) {
        setSingleSelection(nextRow.key);
      }
      return;
    }

    if (event.key === "ArrowLeft" && currentRow) {
      event.preventDefault();
      if (currentRow.kind === "folder" && !currentRow.isDraft && expanded.has(currentRow.path)) {
        handleToggleFolder(currentRow);
        return;
      }
      const parentPath = currentRow.kind === "folder" ? currentRow.parentPath : currentRow.path;
      if (!parentPath) return;
      const parentKey = folderRowKey(parentPath);
      if (rowsByKey.has(parentKey)) {
        setSingleSelection(parentKey);
      }
      return;
    }

    if (event.key === "Enter" && currentRow?.kind === "folder" && !currentRow.isDraft) {
      event.preventDefault();
      handleToggleFolder(currentRow);
    }
  }, [
    clipboard,
    currentActionFolderPath,
    expanded,
    focusedKey,
    handleCopyRows,
    handlePasteItems,
    handleToggleFolder,
    primaryRow,
    renamingKey,
    rowsByKey,
    selectedRows,
    setRangeSelection,
    setSingleSelection,
    visibleRows,
  ]);

  const handleRowDragStart = useCallback((event: React.DragEvent<HTMLDivElement>, row: ExplorerRow) => {
    if (row.isDraft) {
      event.preventDefault();
      return;
    }

    const persistedSelection = new Set(
      (selectedKeys.has(row.key) ? [...selectedKeys] : [row.key]).filter((key) => {
        const selectedRow = rowsByKey.get(key);
        return Boolean(selectedRow && !selectedRow.isDraft);
      }),
    );
    if (persistedSelection.size === 0) {
      event.preventDefault();
      return;
    }

    if (!selectedKeys.has(row.key) || persistedSelection.size !== selectedKeys.size) {
      setSelectedKeys(persistedSelection);
      setFocusedKey(row.key);
      setAnchorKey(row.key);
    }

    setDraggedKeys(persistedSelection);
    setDragOverPath(null);
    dragCancelledRef.current = false;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", [...persistedSelection].join(","));

    const badge = document.createElement("div");
    badge.className = "priors-drag-badge";
    badge.textContent = String(persistedSelection.size);
    document.body.appendChild(badge);
    event.dataTransfer.setDragImage(badge, 12, 12);
    window.requestAnimationFrame(() => {
      badge.remove();
    });
  }, [rowsByKey, selectedKeys]);

  const handleRowDragOver = useCallback((event: React.DragEvent<HTMLDivElement>, row: ExplorerRow) => {
    if (row.kind !== "folder" || row.isDraft || draggedKeys.size === 0) return;
    const draggedRows = [...draggedKeys]
      .map((key) => rowsByKey.get(key))
      .filter((candidate): candidate is ExplorerRow => Boolean(candidate));
    const invalid = draggedRows.some((candidate) => candidate.kind === "folder" && (candidate.path === row.path || isDescendantPath(row.path, candidate.path)));
    if (invalid) return;

    event.preventDefault();
    if (dragOverPath !== row.path) {
      setDragOverPath(row.path);
      if (dragExpandTimerRef.current !== null) {
        window.clearTimeout(dragExpandTimerRef.current);
      }
      if (!expanded.has(row.path)) {
        dragExpandTimerRef.current = window.setTimeout(() => {
          setExpanded((prev) => {
            if (prev.has(row.path)) return prev;
            const next = new Set(prev).add(row.path);
            expandedRef.current = next;
            return next;
          });
          if (!folderMap[row.path]) {
            void fetchFolder(row.path);
          }
        }, 900);
      }
    }
  }, [dragOverPath, draggedKeys, expanded, fetchFolder, folderMap, rowsByKey]);

  const handleRowDragLeave = useCallback((event: React.DragEvent<HTMLDivElement>, row: ExplorerRow) => {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    if (dragOverPath === row.path) {
      setDragOverPath(null);
    }
    if (dragExpandTimerRef.current !== null) {
      window.clearTimeout(dragExpandTimerRef.current);
      dragExpandTimerRef.current = null;
    }
  }, [dragOverPath]);

  const handleRowDrop = useCallback((event: React.DragEvent<HTMLDivElement>, row: ExplorerRow) => {
    if (row.kind !== "folder" || row.isDraft || draggedKeys.size === 0) return;
    event.preventDefault();
    if (dragCancelledRef.current) {
      return;
    }
    const keys = [...draggedKeys];
    clearDragState();
    void handleMoveSelection(keys, row.path);
  }, [clearDragState, draggedKeys, handleMoveSelection]);

  const breadcrumbItems = useMemo(() => {
    const items: Array<{ label: string; to?: string }> = [
      { label: "Projects", to: "/" },
      { label: projectName, to: `/project/${projectId}` },
    ];

    if (singleSelectedRow?.kind === "prior") {
      items.push({ label: "SovaraDB", to: `/project/${projectId}/priors` });
      items.push({ label: displayPriorName(singleSelectedRow.name) });
      return items;
    }

    items.push({ label: "SovaraDB" });
    return items;
  }, [projectId, projectName, singleSelectedRow]);

  const emptySelectionMessage = selectedRows.length > 1
    ? `${selectedRows.length} items selected. Choose one prior to edit its contents.`
    : "No prior selected. Open one to see and edit its contents.";

  return (
    <div className="priors-page">
      <Breadcrumb items={breadcrumbItems} />

      {systemToast && (
        <SystemToast toast={systemToast} onClose={() => setSystemToast(null)} />
      )}

      <div className="priors-body">
        <div className="priors-explorer">
          <div className="priors-explorer-header">
            <span className="priors-explorer-title">SovaraDB</span>
            <div className="priors-explorer-actions">
              <button
                type="button"
                title="New Prior"
                onClick={() => {
                  void handleCreateDraftPrior(currentActionFolderPath);
                }}
                disabled={saving}
              >
                <Plus size={14} />
              </button>
              <button
                type="button"
                title="New Folder"
                onClick={() => {
                  void handleCreateDraftFolder(currentActionFolderPath);
                }}
                disabled={saving}
              >
                <FolderPlus size={14} />
              </button>
            </div>
          </div>

          <div
            ref={treeRef}
            className="priors-tree"
            tabIndex={0}
            onKeyDown={handleTreeKeyDown}
            onDragOver={(event) => {
              if (draggedKeys.size === 0) return;
              if (event.target !== event.currentTarget) return;
              event.preventDefault();
              setDragOverPath("");
            }}
            onDragLeave={(event) => {
              if (event.target === event.currentTarget) {
                setDragOverPath(null);
              }
            }}
            onDrop={(event) => {
              if (draggedKeys.size === 0) return;
              if (event.target !== event.currentTarget) return;
              event.preventDefault();
              if (dragCancelledRef.current) {
                return;
              }
              const keys = [...draggedKeys];
              clearDragState();
              void handleMoveSelection(keys, "");
            }}
            onClick={(event) => {
              if (event.target === event.currentTarget) {
                setSingleSelection(null);
                setContextMenu(null);
              }
            }}
            onContextMenu={(event) => {
              if (event.target !== event.currentTarget) return;
              event.preventDefault();
              treeRef.current?.focus();
              setSingleSelection(null);
              setContextMenu({
                x: event.clientX,
                y: event.clientY,
                selectionKeys: [],
                backgroundPath: "",
              });
            }}
          >
            {explorerLoading && visibleRows.length === 0 ? (
              <div className="priors-editor-empty" style={{ height: "160px" }}>
                <Loader2 size={24} className="spin" />
                <p>Loading priors...</p>
              </div>
            ) : (
              visibleRows.map((row) => (
                <ExplorerRowView
                  key={row.key}
                  row={row}
                  selected={selectedKeys.has(row.key)}
                  focused={focusedKey === row.key}
                  renaming={renamingKey === row.key}
                  dragOver={dragOverPath === row.path && row.kind === "folder"}
                  draggable={!row.isDraft}
                  loading={loadingPaths.has(row.kind === "folder" ? row.path : row.parentPath)}
                  rowRef={(node) => {
                    rowRefs.current[row.key] = node;
                  }}
                  onSelect={handleRowClick}
                  onToggle={handleToggleFolder}
                  onDragStart={handleRowDragStart}
                  onDragOver={handleRowDragOver}
                  onDragLeave={handleRowDragLeave}
                  onDrop={handleRowDrop}
                  onDragEnd={clearDragState}
                  onRenameSubmit={(targetRow, name) => {
                    void handleRenameSubmit(targetRow, name);
                  }}
                  onRenameCancel={() => setRenamingKey(null)}
                  onContextMenu={(event, targetRow) => {
                    event.preventDefault();
                    treeRef.current?.focus();
                    const nextKeys = selectedKeys.has(targetRow.key) ? [...selectedKeys] : [targetRow.key];
                    if (!selectedKeys.has(targetRow.key)) {
                      setSelectedKeys(new Set(nextKeys));
                      setFocusedKey(targetRow.key);
                      setAnchorKey(targetRow.key);
                    }
                    setContextMenu({
                      x: event.clientX,
                      y: event.clientY,
                      selectionKeys: nextKeys,
                      backgroundPath: targetRow.kind === "folder" ? targetRow.path : targetRow.path,
                    });
                  }}
                />
              ))
            )}
          </div>
        </div>

        <div className="priors-editor-panel">
          <PathBar
            folderPath={currentBarFolderPath}
            priorName={currentBarPriorName}
            onNavigate={(path) => {
              ensureFolderExpanded(path);
              const key = folderRowKey(path);
              if (path && rowsByKey.has(key)) {
                setSingleSelection(key);
              } else {
                setSingleSelection(null);
              }
            }}
          />

          {selectedPrior ? (
            selectedPriorLoading ? (
              <div className="priors-editor-empty">
                <Loader2 size={24} className="spin" />
                <p>Loading prior...</p>
              </div>
            ) : (
              <SplitEditor
                key={selectedPrior.draftKey ?? selectedPrior.id}
                filename={displayPriorName(selectedPrior.name)}
                value={selectedPrior.content ?? ""}
                draftMode={isDraftPriorRecord(selectedPrior)}
                saving={saving}
                editorAction={editorAction}
                review={reviewResult}
                reviewLoading={reviewLoading}
                reviewSaved={reviewSaved}
                onSave={(nextContent) => {
                  void handleSaveContent(nextContent);
                }}
                onSubmit={isDraftPriorRecord(selectedPrior) ? (nextContent) => {
                  void handleSubmitDraft(nextContent);
                } : undefined}
              />
            )
          ) : (
            <div className="priors-editor-empty">
              <FileText size={32} />
              <p>{emptySelectionMessage}</p>
            </div>
          )}
        </div>
      </div>

      {contextMenu && contextMenuActions.length > 0 && (
        <ContextMenu
          state={contextMenu}
          actions={contextMenuActions}
          onClose={() => setContextMenu(null)}
        />
      )}

      {deleteDialog && (
        <ConfirmDialog
          message={
            deleteDialog.keys.length === 1
              ? "Delete the selected item?"
              : `Delete ${deleteDialog.keys.length} selected items?`
          }
          onConfirm={() => {
            void handleDeleteSelection(deleteDialog.keys);
          }}
          onCancel={() => setDeleteDialog(null)}
        />
      )}

      {moveDialog && (
        <MoveDialog
          destinationPath={moveDialog.destinationPath}
          rows={moveDialogRows}
          disabledPaths={moveDialogDisabledPaths}
          onSelectDestination={(path) => setMoveDialog((current) => (current ? { ...current, destinationPath: path } : current))}
          onToggleFolder={handleToggleFolder}
          onConfirm={() => {
            void handleMoveSelection(moveDialog.keys, moveDialog.destinationPath);
          }}
          onCancel={() => setMoveDialog(null)}
        />
      )}
    </div>
  );
}
