import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { X } from "lucide-react";
import { deleteRuns } from "../api";
import type { CustomMetricColumn } from "../api";
import { Breadcrumb } from "../components/Breadcrumb";
import { CompletedRunsTable } from "../components/CompletedRunsTable";
import { CompletedRunsToolbar, RunActionsMenu } from "../components/CompletedRunsToolbar";
import { PaginationBar } from "../components/PaginationBar";
import { ProjectFilterPanel } from "../components/ProjectFilterPanel";
import { RunningRunsSection } from "../components/RunningRunsSection";
import { useCompletedSelection } from "../hooks/useCompletedSelection";
import { useProjectExperimentsData } from "../hooks/useProjectExperimentsData";
import { computeDataBounds, emptyFilters, isMetricFilterActive, serializeFilters, type Filters } from "../projectFilters";
import { useStoredSortState, type SortState } from "../hooks/useStoredSortState";
import { experimentToProjectRun, formatProjectRunTimestamp, sortProjectRuns } from "../projectRuns";

// ── Sorting ──────────────────────────────────────────────

const DEFAULT_SORT: SortState = { key: "timestamp", direction: "desc" };
const COMPLETED_BUILTIN_COLUMNS = [
  { key: "name", label: "Run Name" },
  { key: "timestamp", label: "Start Time" },
  { key: "sessionId", label: "Session ID" },
  { key: "codeVersion", label: "Version" },
  { key: "tags", label: "Tags" },
  { key: "latency", label: "Latency" },
  { key: "thumbLabel", label: "Label" },
] as const;

function loadHiddenColumns(storageKey: string): Set<string> {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? new Set(parsed.filter((value): value is string => typeof value === "string")) : new Set();
  } catch {
    return new Set();
  }
}

// ── Main Page ────────────────────────────────────────────

export function ProjectPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();

  // Filters
  const [filters, setFilters] = useState<Filters>(() => emptyFilters());
  const filterKey = useMemo(() => serializeFilters(filters), [filters]);

  // Selection (completed runs only)
  const [actionsState, setActionsState] = useState<{ contextKey: string; open: boolean }>({
    contextKey: "",
    open: false,
  });
  const actionsRef = useRef<HTMLDivElement>(null);
  const columnsRef = useRef<HTMLDivElement>(null);
  const contextMenuRef = useRef<HTMLDivElement>(null);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<{
    open: boolean;
    x: number;
    y: number;
    targetIds: string[];
  }>({
    open: false,
    x: 0,
    y: 0,
    targetIds: [],
  });

  // Running: pagination + sort
  const [runningRowsPerPage, setRunningRowsPerPage] = useState(10);
  const [runningPage, setRunningPage] = useState(1);
  const [runningSort, setRunningSort] = useStoredSortState({
    fallbackState: DEFAULT_SORT,
    storageKey: `web_app:project_sort:${projectId ?? "unknown"}:running`,
  });

  // Completed: pagination + sort
  const [completedRowsPerPage, setCompletedRowsPerPage] = useState(50);
  const [completedPage, setCompletedPage] = useState(1);
  const [completedSort, setCompletedSort] = useStoredSortState({
    fallbackState: DEFAULT_SORT,
    storageKey: `web_app:project_sort:${projectId ?? "unknown"}:completed`,
  });
  const {
    completedExperiments,
    completedTotal,
    customMetricColumns,
    distinctVersions,
    loading,
    projectName,
    projectTags,
    runningExperiments,
  } = useProjectExperimentsData({
    completedPage,
    completedRowsPerPage,
    completedSort,
    filters,
    projectId,
  });
  const runningRuns = useMemo(() => runningExperiments.map(experimentToProjectRun), [runningExperiments]);
  const completedRuns = useMemo(() => completedExperiments.map(experimentToProjectRun), [completedExperiments]);
  const bounds = useMemo(() => computeDataBounds([...runningRuns, ...completedRuns]), [runningRuns, completedRuns]);
  const columnStorageKey = useMemo(
    () => `web_app:project_columns:${projectId ?? "unknown"}`,
    [projectId],
  );
  const [hiddenColumnKeys, setHiddenColumnKeys] = useState<Set<string>>(() => loadHiddenColumns(columnStorageKey));
  useEffect(() => {
    setHiddenColumnKeys(loadHiddenColumns(columnStorageKey));
  }, [columnStorageKey]);
  useEffect(() => {
    try {
      localStorage.setItem(columnStorageKey, JSON.stringify(Array.from(hiddenColumnKeys).sort()));
    } catch {
      // Ignore storage failures; in-memory visibility still works.
    }
  }, [columnStorageKey, hiddenColumnKeys]);

  const columnOptions = useMemo(() => {
    const metricOptions = customMetricColumns.map((column: CustomMetricColumn) => ({
      key: `metric:${column.key}`,
      label: column.key,
    }));
    return [...COMPLETED_BUILTIN_COLUMNS, ...metricOptions];
  }, [customMetricColumns]);
  const selectedColumnKeys = useMemo(
    () => new Set(columnOptions.map((column) => column.key).filter((key) => !hiddenColumnKeys.has(key))),
    [columnOptions, hiddenColumnKeys],
  );
  const allColumnsVisible = selectedColumnKeys.size === columnOptions.length;
  const filtersActive = useMemo(
    () => Boolean(
      filters.name.value
      || filters.sessionId
      || filters.version.size > 0
      || filters.tags.size > 0
      || filters.label.size > 0
      || filters.startTime.from
      || filters.startTime.to
      || filters.latency.min > bounds.latency.min
      || filters.latency.max < bounds.latency.max
      || Object.values(filters.customMetrics).some((filter) => isMetricFilterActive(filter))
    ),
    [bounds.latency.max, bounds.latency.min, filters],
  );

  const handleSetFilters = useCallback((newFilters: Filters) => {
    setFilters(newFilters);
    setCompletedPage(1);
  }, []);

  const handleRunningSort = useCallback((key: string) => {
    setRunningSort((prev: SortState) => {
      if (prev?.key === key) return prev.direction === "asc" ? { key, direction: "desc" } : null;
      return { key, direction: "asc" };
    });
  }, [setRunningSort]);

  const handleRowKeyDown = useCallback((event: React.KeyboardEvent<HTMLTableRowElement>, sessionId: string) => {
    if (event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    navigate(`/project/${projectId}/run/${sessionId}`);
  }, [navigate, projectId]);

  const handleCompletedSort = useCallback((key: string) => {
    setCompletedSort((prev: SortState) => {
      if (prev?.key === key) return prev.direction === "asc" ? { key, direction: "desc" } : null;
      return { key, direction: "asc" };
    });
    setCompletedPage(1);
  }, [setCompletedSort]);

  // Running: client-side sort/paginate (no filters applied)
  const allRunning = runningRuns;
  const sortedRunning = useMemo(() => sortProjectRuns(allRunning, runningSort), [allRunning, runningSort]);
  const runningTotalPages = Math.max(1, Math.ceil(sortedRunning.length / runningRowsPerPage));
  const safeRunningPage = Math.min(runningPage, runningTotalPages);
  const running = sortedRunning.slice((safeRunningPage - 1) * runningRowsPerPage, safeRunningPage * runningRowsPerPage);

  // Completed: server-side filter/sort/paginate
  const completedTotalPages = Math.max(1, Math.ceil(completedTotal / completedRowsPerPage));
  const safeCompletedPage = Math.min(completedPage, completedTotalPages);
  const completed = completedRuns;
  const visibleCompletedIds = useMemo(() => completed.map((run) => run.id), [completed]);
  const {
    allVisibleSelected,
    clearSelection: clearCompletedSelection,
    hiddenSelectedCount,
    removeSelection: removeCompletedSelection,
    selectedCount: selectedCompletedCount,
    selectedIds: selectedCompleted,
    toggleSelect: toggleCompletedSelect,
    toggleSelectAllVisible: toggleCompletedSelectAll,
  } = useCompletedSelection({
    filterKey,
    projectId,
    visibleIds: visibleCompletedIds,
  });
  const actionsContextKey = useMemo(
    () => `${projectId ?? ""}:${filterKey}:${Array.from(selectedCompleted).sort().join(",")}`,
    [projectId, filterKey, selectedCompleted],
  );
  const actionsOpen = actionsState.open && actionsState.contextKey === actionsContextKey && selectedCompletedCount > 0;
  const activeActionIds = contextMenu.open ? contextMenu.targetIds : Array.from(selectedCompleted);

  const closeContextMenu = useCallback(() => {
    setContextMenu({ open: false, x: 0, y: 0, targetIds: [] });
  }, []);

  useEffect(() => {
    if (!actionsOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (actionsRef.current && !actionsRef.current.contains(e.target as Node)) {
        setActionsState({ contextKey: actionsContextKey, open: false });
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [actionsContextKey, actionsOpen]);
  useEffect(() => {
    if (!contextMenu.open) return;
    const handleClick = (event: MouseEvent) => {
      if (contextMenuRef.current && !contextMenuRef.current.contains(event.target as Node)) {
        closeContextMenu();
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeContextMenu();
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [closeContextMenu, contextMenu.open]);
  useEffect(() => {
    if (!columnsOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (columnsRef.current && !columnsRef.current.contains(e.target as Node)) {
        setColumnsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [columnsOpen]);
  useEffect(() => {
    if (!filtersOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFiltersOpen(false);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [filtersOpen]);

  const handleDeleteRuns = useCallback(async (sessionIds: string[]) => {
    if (sessionIds.length === 0) return;
    try {
      await deleteRuns(sessionIds);
      removeCompletedSelection(sessionIds);
      closeContextMenu();
      setActionsState({ contextKey: actionsContextKey, open: false });
    } catch (error) {
      closeContextMenu();
      setActionsState({ contextKey: actionsContextKey, open: false });
      const message = error instanceof Error ? error.message : "Failed to delete runs.";
      window.alert(message);
    }
  }, [actionsContextKey, closeContextMenu, removeCompletedSelection]);

  const handleOpenRuns = useCallback((sessionIds: string[]) => {
    if (sessionIds.length === 0) return;
    closeContextMenu();
    setActionsState({ contextKey: actionsContextKey, open: false });
    navigate(`/project/${projectId}/run/${sessionIds.join(",")}`);
  }, [actionsContextKey, closeContextMenu, navigate, projectId]);

  const handleAskSovara = useCallback(() => {
    closeContextMenu();
    setActionsState({ contextKey: actionsContextKey, open: false });
    navigate(`/project/${projectId}/sovara`);
  }, [actionsContextKey, closeContextMenu, navigate, projectId]);

  const handleCompletedRowContextMenu = useCallback((event: React.MouseEvent<HTMLTableRowElement>, sessionId: string) => {
    event.preventDefault();
    setColumnsOpen(false);
    setActionsState({ contextKey: actionsContextKey, open: false });
    setFiltersOpen(false);

    setContextMenu({
      open: true,
      x: event.clientX,
      y: event.clientY,
      targetIds: [sessionId],
    });
  }, [actionsContextKey]);

  if (loading) {
    return (
      <div className="project-page">
        <div className="empty-state">
          <div className="empty-state-title">Loading...</div>
        </div>
      </div>
    );
  }

  if (!projectName) {
    return (
      <div className="project-page">
        <div className="empty-state">
          <div className="empty-state-title">Project not found</div>
        </div>
      </div>
    );
  }

  return (
    <div className="project-page">
      <Breadcrumb
        items={[
          { label: "Projects", to: "/" },
          { label: projectName },
        ]}
      />

      <div className="project-page-header">
        <div className="project-page-title">{projectName}</div>
      </div>

      <div className="project-runs-layout">
        <RunningRunsSection
          currentPage={safeRunningPage}
          formatTimestamp={formatProjectRunTimestamp}
          onOpenRun={(sessionId) => navigate(`/project/${projectId}/run/${sessionId}`)}
          onRowKeyDown={handleRowKeyDown}
          onSort={handleRunningSort}
          rows={running}
          rowsPerPage={runningRowsPerPage}
          setCurrentPage={setRunningPage}
          setRowsPerPage={setRunningRowsPerPage}
          sort={runningSort}
          totalCount={allRunning.length}
          totalPages={runningTotalPages}
        />

        {/* Completed runs section */}
        <div className="runs-section completed-runs-section">
          <CompletedRunsToolbar
            actionsOpen={actionsOpen}
            actionsRef={actionsRef}
            allColumnsVisible={allColumnsVisible}
            columnOptions={columnOptions}
            columnsOpen={columnsOpen}
            columnsRef={columnsRef}
            completedTotal={completedTotal}
            filtersActive={filtersActive}
            filtersOpen={filtersOpen}
            hiddenSelectedCount={hiddenSelectedCount}
            onAskSovara={handleAskSovara}
            onClearSelection={() => {
              closeContextMenu();
              setActionsState({ contextKey: actionsContextKey, open: false });
              clearCompletedSelection();
            }}
            onDeleteSelected={() => {
              void handleDeleteRuns(Array.from(selectedCompleted));
            }}
            onOpenSelectedRuns={() => {
              handleOpenRuns(Array.from(selectedCompleted));
            }}
            onSelectAllColumns={() => setHiddenColumnKeys(new Set())}
            onToggleActions={() => {
              closeContextMenu();
              setFiltersOpen(false);
              if (selectedCompletedCount === 0) return;
              setActionsState((prev) => ({
                contextKey: actionsContextKey,
                open: !(prev.open && prev.contextKey === actionsContextKey),
              }));
            }}
            onToggleColumn={(key) => {
              setHiddenColumnKeys((prev) => {
                const next = new Set(prev);
                if (next.has(key)) next.delete(key);
                else next.add(key);
                return next;
              });
            }}
            onToggleColumns={() => {
              closeContextMenu();
              setFiltersOpen(false);
              setColumnsOpen((prev) => !prev);
            }}
            onToggleFilters={() => {
              closeContextMenu();
              setActionsState({ contextKey: actionsContextKey, open: false });
              setColumnsOpen(false);
              setFiltersOpen((prev) => !prev);
            }}
            selectedColumnKeys={selectedColumnKeys}
            selectedCount={selectedCompletedCount}
          />
          <div className="runs-section-scroll">
            <CompletedRunsTable
              allVisibleSelected={allVisibleSelected}
              formatTimestamp={formatProjectRunTimestamp}
              metricColumns={customMetricColumns}
              onOpenRun={(sessionId) => navigate(`/project/${projectId}/run/${sessionId}`)}
              onRowKeyDown={handleRowKeyDown}
              onRowContextMenu={handleCompletedRowContextMenu}
              onSort={handleCompletedSort}
              onToggleSelect={toggleCompletedSelect}
              onToggleSelectAll={toggleCompletedSelectAll}
              runs={completed}
              selectedIds={selectedCompleted}
              sort={completedSort}
              visibleColumnKeys={selectedColumnKeys}
            />
          </div>
          <PaginationBar
            rowsPerPage={completedRowsPerPage}
            setRowsPerPage={setCompletedRowsPerPage}
            currentPage={safeCompletedPage}
            setCurrentPage={setCompletedPage}
            totalPages={completedTotalPages}
          />

        </div>
      </div>
      {contextMenu.open && (
        <div ref={contextMenuRef}>
          <RunActionsMenu
            className="actions-dropdown-menu actions-context-menu"
            style={{ top: contextMenu.y, left: contextMenu.x }}
            onAskSovara={handleAskSovara}
            onDeleteSelected={() => {
              void handleDeleteRuns(activeActionIds);
            }}
            onOpenSelectedRuns={() => {
              handleOpenRuns(activeActionIds);
            }}
          />
        </div>
      )}
      {filtersOpen && (
        <div className="modal-overlay filters-modal-overlay" onClick={() => setFiltersOpen(false)}>
          <div className="modal modal-wide filters-modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Filters</h2>
              <button className="modal-close" onClick={() => setFiltersOpen(false)}>
                <X size={16} />
              </button>
            </div>
            <ProjectFilterPanel
              bounds={bounds}
              distinctVersions={distinctVersions}
              filters={filters}
              metricColumns={customMetricColumns}
              projectTags={projectTags}
              setFilters={handleSetFilters}
            />
          </div>
        </div>
      )}
    </div>
  );
}
