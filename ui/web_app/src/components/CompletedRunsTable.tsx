import type { KeyboardEvent, MouseEvent } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";

import type { CustomMetricColumn } from "../runsApi";
import type { SortState } from "../hooks/useStoredSortState";
import type { ProjectRun } from "../projectRuns";
import { SortableHeader } from "./SortableHeader";
import { TagBadge } from "./TagDropdown";

function formatCustomMetricValue(value: boolean | number | undefined) {
  if (value === undefined) return "—";
  if (typeof value === "boolean") return value ? "True" : "False";
  return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/\.?0+$/, "");
}

export function CompletedRunsTable({
  allVisibleSelected,
  formatCodeVersion,
  formatTimestamp,
  metricColumns,
  onOpenRun,
  onRowKeyDown,
  onRowContextMenu,
  onSort,
  onToggleSelect,
  onToggleSelectAll,
  runs,
  selectedIds,
  sort,
  visibleColumnKeys,
}: {
  allVisibleSelected: boolean;
  formatCodeVersion: (raw: string) => string;
  formatTimestamp: (raw: string) => string;
  metricColumns: CustomMetricColumn[];
  onOpenRun: (runId: string) => void;
  onRowKeyDown: (event: KeyboardEvent<HTMLTableRowElement>, runId: string) => void;
  onRowContextMenu: (event: MouseEvent<HTMLTableRowElement>, runId: string) => void;
  onSort: (key: string) => void;
  onToggleSelect: (id: string) => void;
  onToggleSelectAll: () => void;
  runs: ProjectRun[];
  selectedIds: Set<string>;
  sort: SortState;
  visibleColumnKeys: Set<string>;
}) {
  const show = (key: string) => visibleColumnKeys.has(key);
  const visibleMetricColumns = metricColumns.filter((column) => show(`metric:${column.key}`));
  const showMetricGroupHeader = visibleMetricColumns.length > 1;
  const leadingColumnCount = 1
    + ["timestamp", "name", "codeVersion", "tags", "latency", "thumbLabel"].filter(show).length;

  return (
    <table className="runs-table">
      <thead>
        {showMetricGroupHeader && (
          <tr className="header-group-row">
            <th colSpan={leadingColumnCount} />
            <th className="header-group-label" colSpan={visibleMetricColumns.length}>CUSTOM METRICS</th>
          </tr>
        )}
        <tr>
          <th className="cell-checkbox">
            <input
              type="checkbox"
              checked={allVisibleSelected}
              onChange={onToggleSelectAll}
            />
          </th>
          {show("name") && <SortableHeader label="Run Name" sortKey="name" sort={sort} onSort={onSort} />}
          {show("timestamp") && <SortableHeader label="Start Time" sortKey="timestamp" sort={sort} onSort={onSort} />}
          {show("codeVersion") && <SortableHeader label="Code Version" sortKey="codeVersion" sort={sort} onSort={onSort} />}
          {show("tags") && <th>Tags</th>}
          {show("latency") && <SortableHeader label="Runtime" sortKey="latency" sort={sort} onSort={onSort} />}
          {show("thumbLabel") && <SortableHeader label="Label" sortKey="label" sort={sort} onSort={onSort} />}
          {visibleMetricColumns.map((column) => (
            <SortableHeader
              key={column.key}
              label={column.key}
              sortKey={`metric:${column.key}`}
              sort={sort}
              onSort={onSort}
            />
          ))}
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr
            key={run.id}
            className="clickable-row"
            onClick={() => onOpenRun(run.runId)}
            onContextMenu={(event) => onRowContextMenu(event, run.runId)}
            onKeyDown={(event) => onRowKeyDown(event, run.runId)}
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
            {show("name") && <td>{run.name}</td>}
            {show("timestamp") && <td className="cell-timestamp">{formatTimestamp(run.timestamp)}</td>}
            {show("codeVersion") && <td><span className="cell-id-link">{formatCodeVersion(run.codeVersion)}</span></td>}
            {show("tags") && (
              <td className="cell-tags">
                {run.tags.length > 0 ? run.tags.map((tag) => (
                  <TagBadge key={tag.tag_id} tag={tag} size="small" />
                )) : "—"}
              </td>
            )}
            {show("latency") && <td className="cell-metric">{run.latency}</td>}
            {show("thumbLabel") && (
              <td className="cell-metric">
                {run.thumbLabel === null ? (
                  "—"
                ) : run.thumbLabel ? (
                  <span className="metric-badge success"><ThumbsUp size={12} /></span>
                ) : (
                  <span className="metric-badge fail"><ThumbsDown size={12} /></span>
                )}
              </td>
            )}
            {visibleMetricColumns.map((column) => (
              <td key={column.key} className="cell-metric">
                {formatCustomMetricValue(run.customMetrics[column.key])}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
