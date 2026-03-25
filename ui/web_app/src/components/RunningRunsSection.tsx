import { useEffect, useState } from "react";
import { SortableHeader } from "./SortableHeader";
import { PaginationBar } from "./PaginationBar";
import type { SortState } from "../hooks/useStoredSortState";
import type { ProjectRun } from "../projectRuns";

function LiveTimer({ anchorSeconds }: { anchorSeconds: number | null }) {
  const [elapsedSeconds, setElapsedSeconds] = useState(anchorSeconds);

  useEffect(() => {
    if (anchorSeconds === null) {
      return;
    }
    const interval = window.setInterval(() => {
      setElapsedSeconds((current) => (current === null ? anchorSeconds : current + 1));
    }, 1000);
    return () => window.clearInterval(interval);
  }, [anchorSeconds]);

  if (elapsedSeconds === null) {
    return <span className="live-timer">—</span>;
  }

  return <span className="live-timer">{elapsedSeconds}s</span>;
}

export function RunningRunsSection({
  currentPage,
  formatTimestamp,
  onOpenRun,
  onRowKeyDown,
  onSort,
  rows,
  rowsPerPage,
  setCurrentPage,
  setRowsPerPage,
  sort,
  totalCount,
  totalPages,
}: {
  currentPage: number;
  formatTimestamp: (raw: string) => string;
  onOpenRun: (sessionId: string) => void;
  onRowKeyDown: (event: React.KeyboardEvent<HTMLTableRowElement>, sessionId: string) => void;
  onSort: (key: string) => void;
  rows: ProjectRun[];
  rowsPerPage: number;
  setCurrentPage: (value: number) => void;
  setRowsPerPage: (value: number) => void;
  sort: SortState;
  totalCount: number;
  totalPages: number;
}) {
  return (
    <div className="runs-section running-runs-section">
      <div className="landing-section-title">
        <span className="loading-dot" />
        Running ({totalCount})
      </div>
      <div className="runs-section-scroll">
        <table className="runs-table">
          <thead>
            <tr>
              <SortableHeader label="Run Name" sortKey="name" sort={sort} onSort={onSort} />
              <SortableHeader label="Start Time" sortKey="timestamp" sort={sort} onSort={onSort} />
              <SortableHeader label="Session ID" sortKey="sessionId" sort={sort} onSort={onSort} />
              <SortableHeader label="Version" sortKey="codeVersion" sort={sort} onSort={onSort} />
              <SortableHeader label="Latency" sortKey="latency" sort={sort} onSort={onSort} />
            </tr>
          </thead>
          <tbody>
            {rows.map((run) => (
              <tr
                key={run.id}
                className="clickable-row"
                onClick={() => onOpenRun(run.sessionId)}
                onKeyDown={(event) => onRowKeyDown(event, run.sessionId)}
                tabIndex={0}
                role="link"
                aria-label={`Open run ${run.name}`}
              >
                <td>{run.name}</td>
                <td className="cell-timestamp">{formatTimestamp(run.timestamp)}</td>
                <td><span className="cell-id-link" title={run.sessionId}>{run.sessionId.slice(0, 8)}</span></td>
                <td><span className="cell-id-link">{run.codeVersion}</span></td>
                <td className="cell-metric">
                  <LiveTimer
                    key={`${run.sessionId}:${run.activeRuntimeSeconds ?? "null"}`}
                    anchorSeconds={run.activeRuntimeSeconds}
                  />
                </td>
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
  );
}
