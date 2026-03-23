import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Breadcrumb } from "../components/Breadcrumb";
import { CompletedRunsTable } from "../components/CompletedRunsTable";
import { CompletedRunsToolbar } from "../components/CompletedRunsToolbar";
import { PaginationBar } from "../components/PaginationBar";
import { ProjectFilterPanel } from "../components/ProjectFilterPanel";
import { RunningRunsSection } from "../components/RunningRunsSection";
import { useCompletedSelection } from "../hooks/useCompletedSelection";
import { useProjectExperimentsData } from "../hooks/useProjectExperimentsData";
import { computeDataBounds, emptyFilters, serializeFilters, type Filters } from "../projectFilters";
import { useStoredSortState, type SortState } from "../hooks/useStoredSortState";
import { experimentToProjectRun, formatProjectRunTimestamp, sortProjectRuns } from "../projectRuns";

// ── Sorting ──────────────────────────────────────────────

const DEFAULT_SORT: SortState = { key: "timestamp", direction: "desc" };

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

  // Running: pagination + sort
  const [runningRowsPerPage, setRunningRowsPerPage] = useState(10);
  const [runningPage, setRunningPage] = useState(1);
  const [runningSort, setRunningSort] = useStoredSortState({
    fallbackState: DEFAULT_SORT,
    storageKey: `web_app_v2:project_sort:${projectId ?? "unknown"}:running`,
  });

  // Completed: pagination + sort
  const [completedRowsPerPage, setCompletedRowsPerPage] = useState(50);
  const [completedPage, setCompletedPage] = useState(1);
  const [completedSort, setCompletedSort] = useStoredSortState({
    fallbackState: DEFAULT_SORT,
    storageKey: `web_app_v2:project_sort:${projectId ?? "unknown"}:completed`,
  });
  const {
    completedExperiments,
    completedTotal,
    distinctVersions,
    loading,
    projectName,
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
            completedTotal={completedTotal}
            hiddenSelectedCount={hiddenSelectedCount}
            onAskSovara={() => {
              setActionsState({ contextKey: actionsContextKey, open: false });
              navigate(`/project/${projectId}/sovara`);
            }}
            onClearSelection={() => {
              setActionsState({ contextKey: actionsContextKey, open: false });
              clearCompletedSelection();
            }}
            onDeleteSelected={() => {
              setActionsState({ contextKey: actionsContextKey, open: false });
            }}
            onOpenSelectedRuns={() => {
              const ids = Array.from(selectedCompleted).join(",");
              setActionsState({ contextKey: actionsContextKey, open: false });
              navigate(`/project/${projectId}/run/${ids}`);
            }}
            onToggleActions={() => {
              if (selectedCompletedCount === 0) return;
              setActionsState((prev) => ({
                contextKey: actionsContextKey,
                open: !(prev.open && prev.contextKey === actionsContextKey),
              }));
            }}
            selectedCount={selectedCompletedCount}
          />
          <div className="runs-section-scroll">
            <CompletedRunsTable
              allVisibleSelected={allVisibleSelected}
              formatTimestamp={formatProjectRunTimestamp}
              onOpenRun={(sessionId) => navigate(`/project/${projectId}/run/${sessionId}`)}
              onRowKeyDown={handleRowKeyDown}
              onSort={handleCompletedSort}
              onToggleSelect={toggleCompletedSelect}
              onToggleSelectAll={toggleCompletedSelectAll}
              runs={completed}
              selectedIds={selectedCompleted}
              sort={completedSort}
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
        <ProjectFilterPanel filters={filters} setFilters={handleSetFilters} distinctVersions={distinctVersions} bounds={bounds} />
      </div>
    </div>
  );
}
