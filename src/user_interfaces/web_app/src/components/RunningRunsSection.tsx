import { useEffect, useState } from "react";
import { SortableHeader } from "./SortableHeader";
import { PaginationBar } from "./PaginationBar";
import type { SortState } from "../hooks/useStoredSortState";
import { parseProjectRunTimestamp, type ProjectRun } from "../projectRuns";

function LiveTimer({ startTimestamp }: { startTimestamp: string }) {
  const [elapsed, setElapsed] = useState(() => {
    const start = parseProjectRunTimestamp(startTimestamp);
    return Math.max(0, Math.floor((Date.now() - start) / 1000));
  });

  useEffect(() => {
    const interval = window.setInterval(() => {
      const start = parseProjectRunTimestamp(startTimestamp);
      setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
    }, 1000);
    return () => window.clearInterval(interval);
  }, [startTimestamp]);

  return <span className="live-timer">{elapsed}s</span>;
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
              <SortableHeader label="Start Time" sortKey="timestamp" sort={sort} onSort={onSort} />
              <SortableHeader label="Session ID" sortKey="sessionId" sort={sort} onSort={onSort} />
              <SortableHeader label="Name" sortKey="name" sort={sort} onSort={onSort} />
              <SortableHeader label="Input" sortKey="input" sort={sort} onSort={onSort} />
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
                <td className="cell-timestamp">{formatTimestamp(run.timestamp)}</td>
                <td><span className="cell-id-link">{run.sessionId}</span></td>
                <td>{run.name}</td>
                <td className="cell-content">{run.input}</td>
                <td><span className="cell-id-link">{run.codeVersion}</span></td>
                <td className="cell-metric"><LiveTimer startTimestamp={run.timestamp} /></td>
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
