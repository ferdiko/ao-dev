import type { KeyboardEvent } from "react";
import { SortableHeader } from "./SortableHeader";

type SortDirection = "asc" | "desc";
type SortState = { key: string; direction: SortDirection } | null;

interface CompletedRunRow {
  id: string;
  sessionId: string;
  name: string;
  timestamp: string;
  input: string;
  output: string;
  latency: string;
  cost: string;
  codeVersion: string;
  success: boolean | null;
  confidence: number | null;
  tags: string[];
  comment: string;
}

export function CompletedRunsTable({
  allVisibleSelected,
  onOpenRun,
  onRowKeyDown,
  onSort,
  onToggleSelect,
  onToggleSelectAll,
  runs,
  selectedIds,
  sort,
  formatTimestamp,
}: {
  allVisibleSelected: boolean;
  onOpenRun: (sessionId: string) => void;
  onRowKeyDown: (event: KeyboardEvent<HTMLTableRowElement>, sessionId: string) => void;
  onSort: (key: string) => void;
  onToggleSelect: (id: string) => void;
  onToggleSelectAll: () => void;
  runs: CompletedRunRow[];
  selectedIds: Set<string>;
  sort: SortState;
  formatTimestamp: (raw: string) => string;
}) {
  return (
    <table className="runs-table">
      <thead>
        <tr className="header-group-row">
          <th className="cell-checkbox" />
          <th colSpan={10} />
          <th colSpan={2} className="header-group-label">Custom Metrics</th>
        </tr>
        <tr>
          <th className="cell-checkbox">
            <input
              type="checkbox"
              checked={allVisibleSelected}
              onChange={onToggleSelectAll}
            />
          </th>
          <SortableHeader label="Start Time" sortKey="timestamp" sort={sort} onSort={onSort} />
          <SortableHeader label="Session ID" sortKey="sessionId" sort={sort} onSort={onSort} />
          <SortableHeader label="Name" sortKey="name" sort={sort} onSort={onSort} />
          <SortableHeader label="Input" sortKey="input" sort={sort} onSort={onSort} />
          <SortableHeader label="Output" sortKey="output" sort={sort} onSort={onSort} />
          <SortableHeader label="Version" sortKey="codeVersion" sort={sort} onSort={onSort} />
          <SortableHeader label="Tags" sortKey="tags" sort={sort} onSort={onSort} />
          <SortableHeader label="Comment" sortKey="comment" sort={sort} onSort={onSort} />
          <SortableHeader label="Latency" sortKey="latency" sort={sort} onSort={onSort} />
          <SortableHeader label="Cost" sortKey="cost" sort={sort} onSort={onSort} />
          <SortableHeader label="Success" sortKey="success" sort={sort} onSort={onSort} />
          <SortableHeader label="Confidence" sortKey="confidence" sort={sort} onSort={onSort} />
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr
            key={run.id}
            className="clickable-row"
            onClick={() => onOpenRun(run.sessionId)}
            onKeyDown={(event) => onRowKeyDown(event, run.sessionId)}
            tabIndex={0}
            role="link"
            aria-label={`Open run ${run.name}`}
          >
            <td className="cell-checkbox" onClick={(event) => event.stopPropagation()}>
              <input
                type="checkbox"
                checked={selectedIds.has(run.id)}
                onChange={() => onToggleSelect(run.id)}
              />
            </td>
            <td className="cell-timestamp">{formatTimestamp(run.timestamp)}</td>
            <td><span className="cell-id-link">{run.sessionId}</span></td>
            <td>{run.name}</td>
            <td className="cell-content">{run.input}</td>
            <td className="cell-content">{run.output || "—"}</td>
            <td><span className="cell-id-link">{run.codeVersion}</span></td>
            <td className="cell-tags">{"—"}</td>
            <td className="cell-comment">{run.comment || "—"}</td>
            <td className="cell-metric">{run.latency}</td>
            <td className="cell-metric">{run.cost}</td>
            <td className="cell-metric">
              {run.success === null ? "—" : run.success ? (
                <span className="metric-badge success">Pass</span>
              ) : (
                <span className="metric-badge fail">Fail</span>
              )}
            </td>
            <td className="cell-metric">
              {run.confidence === null ? "—" : `${run.confidence}%`}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
