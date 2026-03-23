import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Search, X, ChevronDown as ChevronDownIcon } from "lucide-react";
import { Breadcrumb } from "../components/Breadcrumb";
import { CompletedRunsTable } from "../components/CompletedRunsTable";
import { CompletedRunsToolbar } from "../components/CompletedRunsToolbar";
import { SortableHeader } from "../components/SortableHeader";
import { fetchProject, fetchProjectExperiments } from "../api";
import type { Experiment, ExperimentQueryParams } from "../api";
import { useCompletedSelection } from "../hooks/useCompletedSelection";
import { useStoredSortState } from "../hooks/useStoredSortState";
import { subscribe } from "../serverEvents";

const ROWS_PER_PAGE_OPTIONS = [10, 20, 50, 100];

interface Run {
  id: string;
  sessionId: string;
  name: string;
  status: "running" | "finished";
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

function experimentToRun(exp: Experiment): Run {
  return {
    id: exp.session_id,
    sessionId: exp.session_id,
    name: exp.run_name,
    status: exp.status === "running" ? "running" : "finished",
    timestamp: exp.timestamp,
    codeVersion: exp.version_date ?? "—",
    success: exp.result === "Satisfactory" ? true : exp.result === "Failed" ? false : null,
    input: "—",
    output: "—",
    latency: "—",
    cost: "—",
    confidence: null,
    tags: [],
    comment: "—",
  };
}

function formatTimestamp(raw: string): string {
  if (!raw) return "—";
  const ms = parseUTCTimestamp(raw);
  if (isNaN(ms)) return raw;
  return new Date(ms).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

// ── Sorting ──────────────────────────────────────────────

type SortDirection = "asc" | "desc";
type SortState = { key: string; direction: SortDirection } | null;

const DEFAULT_SORT: SortState = { key: "timestamp", direction: "desc" };

function parseLatency(val: string): number {
  const n = parseFloat(val);
  return isNaN(n) ? Infinity : n;
}

function parseCost(val: string): number {
  const n = parseFloat(val.replace(/[^0-9.]/g, ""));
  return isNaN(n) ? Infinity : n;
}

function compareRuns(a: Run, b: Run, key: string): number {
  switch (key) {
    case "timestamp": return a.timestamp.localeCompare(b.timestamp);
    case "sessionId": return a.sessionId.localeCompare(b.sessionId);
    case "name": {
      const numA = parseInt(a.name.replace(/^Run\s*/, ""), 10);
      const numB = parseInt(b.name.replace(/^Run\s*/, ""), 10);
      if (!isNaN(numA) && !isNaN(numB)) return numA - numB;
      return a.name.localeCompare(b.name);
    }
    case "input": return a.input.localeCompare(b.input);
    case "output": return (a.output || "").localeCompare(b.output || "");
    case "codeVersion": return a.codeVersion.localeCompare(b.codeVersion);
    case "latency": return parseLatency(a.latency) - parseLatency(b.latency);
    case "success": {
      const va = a.success === null ? -1 : a.success ? 1 : 0;
      const vb = b.success === null ? -1 : b.success ? 1 : 0;
      return va - vb;
    }
    case "confidence": return (a.confidence ?? -1) - (b.confidence ?? -1);
    case "cost": return parseCost(a.cost) - parseCost(b.cost);
    case "tags": return a.tags.join(",").localeCompare(b.tags.join(","));
    case "comment": return a.comment.localeCompare(b.comment);
    default: return 0;
  }
}

function sortRuns(runs: Run[], sort: SortState): Run[] {
  if (!sort) return runs;
  const sorted = [...runs].sort((a, b) => compareRuns(a, b, sort.key));
  return sort.direction === "desc" ? sorted.reverse() : sorted;
}

// ── Subcomponents ────────────────────────────────────────

function parseUTCTimestamp(raw: string): number {
  const normalized = raw.replace(" ", "T");
  return new Date(normalized.endsWith("Z") ? normalized : normalized + "Z").getTime();
}

function LiveTimer({ startTimestamp }: { startTimestamp: string }) {
  const [elapsed, setElapsed] = useState(() => {
    const start = parseUTCTimestamp(startTimestamp);
    return Math.max(0, Math.floor((Date.now() - start) / 1000));
  });

  useEffect(() => {
    const interval = setInterval(() => {
      const start = parseUTCTimestamp(startTimestamp);
      setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
    }, 1000);
    return () => clearInterval(interval);
  }, [startTimestamp]);

  return <span className="live-timer">{elapsed}s</span>;
}

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

// ── Filters ──────────────────────────────────────────────

interface TextFilter {
  value: string;
  isRegex: boolean;
}

interface RangeFilter {
  min: number;
  max: number;
}

interface DateRangeFilter {
  from: string; // ISO date string or ""
  to: string;
}

interface Filters {
  name: TextFilter;
  sessionId: string; // plain contains-only (no regex)
  input: TextFilter;
  output: TextFilter;
  comment: TextFilter;
  version: Set<string>;
  success: Set<string>;
  confidence: RangeFilter;
  latency: RangeFilter;
  cost: RangeFilter;
  startTime: DateRangeFilter;
}

interface DataBounds {
  latency: { min: number; max: number };
  confidence: { min: number; max: number };
  cost: { min: number; max: number };
}

function parseLatencyValue(val: string): number {
  const n = parseFloat(val);
  return isNaN(n) ? 0 : n;
}

function parseCostValue(val: string): number {
  const n = parseFloat(val.replace(/[^0-9.]/g, ""));
  return isNaN(n) ? 0 : n;
}

function computeDataBounds(runs: Run[]): DataBounds {
  let latMin = Infinity, latMax = -Infinity;
  let confMin = Infinity, confMax = -Infinity;
  let costMin = Infinity, costMax = -Infinity;
  for (const r of runs) {
    const lat = parseLatencyValue(r.latency);
    if (lat > 0) { latMin = Math.min(latMin, lat); latMax = Math.max(latMax, lat); }
    if (r.confidence !== null) { confMin = Math.min(confMin, r.confidence); confMax = Math.max(confMax, r.confidence); }
    const c = parseCostValue(r.cost);
    if (c > 0) { costMin = Math.min(costMin, c); costMax = Math.max(costMax, c); }
  }
  return {
    latency: { min: latMin === Infinity ? 0 : Math.floor(latMin), max: latMax === -Infinity ? 100 : Math.ceil(latMax) },
    confidence: { min: confMin === Infinity ? 0 : Math.floor(confMin), max: confMax === -Infinity ? 100 : Math.ceil(confMax) },
    cost: { min: costMin === Infinity ? 0 : Math.floor(costMin * 100) / 100, max: costMax === -Infinity ? 1 : Math.ceil(costMax * 100) / 100 },
  };
}

function emptyFilters(bounds?: DataBounds): Filters {
  return {
    name: { value: "", isRegex: false },
    sessionId: "",
    input: { value: "", isRegex: false },
    output: { value: "", isRegex: false },
    comment: { value: "", isRegex: false },
    version: new Set(),
    success: new Set(),
    confidence: bounds ? { ...bounds.confidence } : { min: 0, max: 100 },
    latency: bounds ? { ...bounds.latency } : { min: 0, max: 100 },
    cost: bounds ? { ...bounds.cost } : { min: 0, max: 1 },
    startTime: { from: "", to: "" },
  };
}

function serializeFilters(filters: Filters): string {
  return JSON.stringify({
    name: filters.name,
    sessionId: filters.sessionId,
    input: filters.input,
    output: filters.output,
    comment: filters.comment,
    version: Array.from(filters.version).sort(),
    success: Array.from(filters.success).sort(),
    confidence: filters.confidence,
    latency: filters.latency,
    cost: filters.cost,
    startTime: filters.startTime,
  });
}

function rangeActive(range: RangeFilter, bounds: { min: number; max: number }): boolean {
  return range.min > bounds.min || range.max < bounds.max;
}

function dateRangeActive(dr: DateRangeFilter): boolean {
  return dr.from !== "" || dr.to !== "";
}

// ── Filter Components ────────────────────────────────────

function TextFilterInput({
  label,
  filter,
  onChange,
  open,
  onToggle,
}: {
  label: string;
  filter: TextFilter;
  onChange: (f: TextFilter) => void;
  open: boolean;
  onToggle: () => void;
}) {
  const hasValue = filter.value.length > 0;
  const isInvalid = filter.isRegex && filter.value.length > 0 && (() => {
    try { new RegExp(filter.value); return false; } catch { return true; }
  })();

  return (
    <div className={`filter-section${open ? " open" : ""}`}>
      <button className="filter-section-header" onClick={onToggle}>
        <span className="filter-label">
          {label}
          {hasValue && <span className="filter-active-dot" />}
        </span>
        <ChevronDownIcon size={12} className={`filter-chevron${open ? " rotated" : ""}`} />
      </button>
      {open && (
        <div className="filter-section-body">
          <div className={`filter-text-input-row${isInvalid ? " invalid" : ""}`}>
            <Search size={12} className="filter-search-icon" />
            <input
              type="text"
              className="filter-text-input"
              placeholder={filter.isRegex ? "Regex pattern..." : "Contains..."}
              value={filter.value}
              onChange={(e) => onChange({ ...filter, value: e.target.value })}
            />
            {hasValue && (
              <button className="filter-clear-btn" onClick={() => onChange({ ...filter, value: "" })}>
                <X size={10} />
              </button>
            )}
          </div>
          <label className="filter-regex-toggle">
            <input
              type="checkbox"
              checked={filter.isRegex}
              onChange={(e) => onChange({ ...filter, isRegex: e.target.checked })}
            />
            <span className="filter-regex-label">Regex</span>
          </label>
        </div>
      )}
    </div>
  );
}

/** Plain text filter without regex option (for Session ID) */
function PlainTextFilterInput({
  label,
  value,
  onChange,
  open,
  onToggle,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  open: boolean;
  onToggle: () => void;
}) {
  const hasValue = value.length > 0;

  return (
    <div className={`filter-section${open ? " open" : ""}`}>
      <button className="filter-section-header" onClick={onToggle}>
        <span className="filter-label">
          {label}
          {hasValue && <span className="filter-active-dot" />}
        </span>
        <ChevronDownIcon size={12} className={`filter-chevron${open ? " rotated" : ""}`} />
      </button>
      {open && (
        <div className="filter-section-body">
          <div className="filter-text-input-row">
            <Search size={12} className="filter-search-icon" />
            <input
              type="text"
              className="filter-text-input"
              placeholder="Contains..."
              value={value}
              onChange={(e) => onChange(e.target.value)}
            />
            {hasValue && (
              <button className="filter-clear-btn" onClick={() => onChange("")}>
                <X size={10} />
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const CHECKBOX_INITIAL_SHOW = 5;

function CheckboxFilterSection({
  label,
  options,
  selected,
  onChange,
  counts,
  open,
  onToggle,
}: {
  label: string;
  options: { value: string; label: string }[];
  selected: Set<string>;
  onChange: (s: Set<string>) => void;
  counts?: Record<string, number>;
  open: boolean;
  onToggle: () => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const hasSelection = selected.size > 0;
  const hasMore = options.length > CHECKBOX_INITIAL_SHOW;
  const visible = showAll || !hasMore ? options : options.slice(0, CHECKBOX_INITIAL_SHOW);

  function toggle(value: string) {
    const next = new Set(selected);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    onChange(next);
  }

  return (
    <div className={`filter-section${open ? " open" : ""}`}>
      <button className="filter-section-header" onClick={onToggle}>
        <span className="filter-label">
          {label}
          {hasSelection && <span className="filter-active-dot" />}
        </span>
        <ChevronDownIcon size={12} className={`filter-chevron${open ? " rotated" : ""}`} />
      </button>
      {open && (
        <div className="filter-section-body">
          {visible.map((opt) => (
            <label key={opt.value} className="filter-checkbox-row">
              <input
                type="checkbox"
                checked={selected.has(opt.value)}
                onChange={() => toggle(opt.value)}
              />
              <span className="filter-checkbox-label">{opt.label}</span>
              {counts && counts[opt.value] !== undefined && (
                <span className="filter-checkbox-count">{counts[opt.value]}</span>
              )}
            </label>
          ))}
          {hasMore && (
            <button
              className="filter-load-more-btn"
              onClick={() => setShowAll(!showAll)}
            >
              {showAll ? "Show less" : `Show ${options.length - CHECKBOX_INITIAL_SHOW} more`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function DateRangeFilterSection({
  label,
  range,
  onChange,
  open,
  onToggle,
}: {
  label: string;
  range: DateRangeFilter;
  onChange: (r: DateRangeFilter) => void;
  open: boolean;
  onToggle: () => void;
}) {
  const isActive = dateRangeActive(range);

  return (
    <div className={`filter-section${open ? " open" : ""}`}>
      <button className="filter-section-header" onClick={onToggle}>
        <span className="filter-label">
          {label}
          {isActive && <span className="filter-active-dot" />}
        </span>
        <ChevronDownIcon size={12} className={`filter-chevron${open ? " rotated" : ""}`} />
      </button>
      {open && (
        <div className="filter-section-body">
          <div className="filter-range-inputs">
            <div className="filter-range-field">
              <span className="filter-range-label">From</span>
              <input
                type="date"
                className="filter-date-input"
                value={range.from}
                onChange={(e) => onChange({ ...range, from: e.target.value })}
              />
            </div>
            <div className="filter-range-field">
              <span className="filter-range-label">To</span>
              <input
                type="date"
                className="filter-date-input"
                value={range.to}
                onChange={(e) => onChange({ ...range, to: e.target.value })}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function RangeFilterSection({
  label,
  range,
  bounds,
  unit,
  step,
  onChange,
  open,
  onToggle,
}: {
  label: string;
  range: RangeFilter;
  bounds: { min: number; max: number };
  unit: string;
  step?: number;
  onChange: (r: RangeFilter) => void;
  open: boolean;
  onToggle: () => void;
}) {
  const isActive = rangeActive(range, bounds);
  const effectiveStep = step ?? 1;

  function commitMin(input: HTMLInputElement) {
    const v = parseFloat(input.value);
    if (isNaN(v)) {
      input.value = String(range.min);
      return;
    }
    const clamped = Math.max(bounds.min, Math.min(v, range.max));
    input.value = String(clamped);
    onChange({ ...range, min: clamped });
  }

  function commitMax(input: HTMLInputElement) {
    const v = parseFloat(input.value);
    if (isNaN(v)) {
      input.value = String(range.max);
      return;
    }
    const clamped = Math.min(bounds.max, Math.max(v, range.min));
    input.value = String(clamped);
    onChange({ ...range, max: clamped });
  }

  const pctMin = bounds.max > bounds.min ? ((range.min - bounds.min) / (bounds.max - bounds.min)) * 100 : 0;
  const pctMax = bounds.max > bounds.min ? ((range.max - bounds.min) / (bounds.max - bounds.min)) * 100 : 100;

  return (
    <div className={`filter-section${open ? " open" : ""}`}>
      <button className="filter-section-header" onClick={onToggle}>
        <span className="filter-label">
          {label}
          {isActive && <span className="filter-active-dot" />}
        </span>
        <ChevronDownIcon size={12} className={`filter-chevron${open ? " rotated" : ""}`} />
      </button>
      {open && (
        <div className="filter-section-body">
          <div className="filter-range-inputs">
            <div className="filter-range-field">
              <span className="filter-range-label">Min.</span>
              <div className="filter-range-input-wrap">
                <input
                  key={`min-${range.min}-${range.max}`}
                  type="text"
                  className="filter-range-input"
                  defaultValue={String(range.min)}
                  onBlur={(e) => commitMin(e.currentTarget)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      commitMin(e.currentTarget);
                      e.currentTarget.blur();
                    }
                  }}
                />
                <span className="filter-range-unit">{unit}</span>
              </div>
            </div>
            <div className="filter-range-field">
              <span className="filter-range-label">Max.</span>
              <div className="filter-range-input-wrap">
                <input
                  key={`max-${range.min}-${range.max}`}
                  type="text"
                  className="filter-range-input"
                  defaultValue={String(range.max)}
                  onBlur={(e) => commitMax(e.currentTarget)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      commitMax(e.currentTarget);
                      e.currentTarget.blur();
                    }
                  }}
                />
                <span className="filter-range-unit">{unit}</span>
              </div>
            </div>
          </div>
          <div className="filter-range-slider">
            <div
              className="filter-range-track-fill"
              style={{ left: `${pctMin}%`, right: `${100 - pctMax}%` }}
            />
            <input
              type="range"
              className="filter-range-thumb filter-range-thumb-min"
              min={bounds.min}
              max={bounds.max}
              step={effectiveStep}
              value={range.min}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                if (v <= range.max) onChange({ ...range, min: v });
              }}
            />
            <input
              type="range"
              className="filter-range-thumb filter-range-thumb-max"
              min={bounds.min}
              max={bounds.max}
              step={effectiveStep}
              value={range.max}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                if (v >= range.min) onChange({ ...range, max: v });
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function FilterPanel({
  filters,
  setFilters,
  distinctVersions,
  bounds,
}: {
  filters: Filters;
  setFilters: (f: Filters) => void;
  distinctVersions: string[];
  bounds: DataBounds;
}) {
  const versionOptions = useMemo(() => ({
    options: distinctVersions.map((v) => ({ value: v, label: v })),
  }), [distinctVersions]);

  const activeCount = [
    filters.name.value,
    filters.sessionId,
    filters.input.value,
    filters.output.value,
    filters.comment.value,
  ].filter(Boolean).length
    + (filters.version.size > 0 ? 1 : 0)
    + (filters.success.size > 0 ? 1 : 0)
    + (rangeActive(filters.latency, bounds.latency) ? 1 : 0)
    + (rangeActive(filters.confidence, bounds.confidence) ? 1 : 0)
    + (rangeActive(filters.cost, bounds.cost) ? 1 : 0)
    + (dateRangeActive(filters.startTime) ? 1 : 0);

  // Section open states (lifted from children for master chevron control)
  const SECTION_KEYS = ["startTime", "name", "sessionId", "input", "output", "comment", "version", "success", "confidence", "latency", "cost"] as const;
  type SectionKey = typeof SECTION_KEYS[number];
  const [openSections, setOpenSections] = useState<Record<SectionKey, boolean>>(
    () => Object.fromEntries(SECTION_KEYS.map((k) => [k, false])) as Record<SectionKey, boolean>
  );
  const toggle = (key: SectionKey) => setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  const anyOpen = SECTION_KEYS.some((k) => openSections[k]);
  const toggleAll = () => {
    const target = !anyOpen; // collapse if any open, expand if all closed
    setOpenSections(Object.fromEntries(SECTION_KEYS.map((k) => [k, target])) as Record<SectionKey, boolean>);
  };

  return (
    <div className="filter-panel">
      <div className="filter-panel-header">
        <span className="filter-panel-title">Filters</span>
        {activeCount > 0 && (
          <button className="filter-reset-btn" onClick={() => setFilters(emptyFilters(bounds))}>
            Reset ({activeCount})
          </button>
        )}
        <button className="filter-expand-all-btn" onClick={toggleAll} title={anyOpen ? "Collapse all" : "Expand all"}>
          <ChevronDownIcon size={14} className={`filter-chevron${anyOpen ? " rotated" : ""}`} />
        </button>
      </div>
      <div className="filter-panel-body">
        <DateRangeFilterSection
          label="Start Time"
          range={filters.startTime}
          onChange={(r) => setFilters({ ...filters, startTime: r })}
          open={openSections.startTime}
          onToggle={() => toggle("startTime")}
        />
        <TextFilterInput
          label="Name"
          filter={filters.name}
          onChange={(f) => setFilters({ ...filters, name: f })}
          open={openSections.name}
          onToggle={() => toggle("name")}
        />
        <PlainTextFilterInput
          label="Session ID"
          value={filters.sessionId}
          onChange={(v) => setFilters({ ...filters, sessionId: v })}
          open={openSections.sessionId}
          onToggle={() => toggle("sessionId")}
        />
        <TextFilterInput
          label="Input"
          filter={filters.input}
          onChange={(f) => setFilters({ ...filters, input: f })}
          open={openSections.input}
          onToggle={() => toggle("input")}
        />
        <TextFilterInput
          label="Output"
          filter={filters.output}
          onChange={(f) => setFilters({ ...filters, output: f })}
          open={openSections.output}
          onToggle={() => toggle("output")}
        />
        <TextFilterInput
          label="Comment"
          filter={filters.comment}
          onChange={(f) => setFilters({ ...filters, comment: f })}
          open={openSections.comment}
          onToggle={() => toggle("comment")}
        />
        <CheckboxFilterSection
          label="Version"
          options={versionOptions.options}
          selected={filters.version}
          onChange={(s) => setFilters({ ...filters, version: s })}
          open={openSections.version}
          onToggle={() => toggle("version")}
        />

        <RangeFilterSection
          label="Latency"
          range={filters.latency}
          bounds={bounds.latency}
          unit="s"
          step={0.1}
          onChange={(r) => setFilters({ ...filters, latency: r })}
          open={openSections.latency}
          onToggle={() => toggle("latency")}
        />
        <RangeFilterSection
          label="Cost"
          range={filters.cost}
          bounds={bounds.cost}
          unit="$"
          step={0.01}
          onChange={(r) => setFilters({ ...filters, cost: r })}
          open={openSections.cost}
          onToggle={() => toggle("cost")}
        />

        {/* ── Custom Metrics group ── */}
        <div className="filter-group">
          <div className="filter-group-label">Custom Metrics</div>
          <CheckboxFilterSection
            label="Success"
            options={[
              { value: "pass", label: "Pass" },
              { value: "fail", label: "Fail" },
              { value: "pending", label: "Pending" },
            ]}
            selected={filters.success}
            onChange={(s) => setFilters({ ...filters, success: s })}
            open={openSections.success}
            onToggle={() => toggle("success")}
          />
          <RangeFilterSection
            label="Confidence"
            range={filters.confidence}
            bounds={bounds.confidence}
            unit="%"
            step={1}
            onChange={(r) => setFilters({ ...filters, confidence: r })}
            open={openSections.confidence}
            onToggle={() => toggle("confidence")}
          />
        </div>
      </div>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────

export function ProjectPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();

  // Data from API
  const [projectName, setProjectName] = useState("");
  const [runningRuns, setRunningRuns] = useState<Run[]>([]);
  const [completedRuns, setCompletedRuns] = useState<Run[]>([]);
  const [completedTotal, setCompletedTotal] = useState(0);
  const [distinctVersions, setDistinctVersions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  // Re-fetch trigger: incremented by WebSocket when experiment list changes
  const [completedRefreshKey, setCompletedRefreshKey] = useState(0);

  // Fetch project name
  const loadProjectName = useCallback(() => {
    if (!projectId) return;
    fetchProject(projectId).then((p) => setProjectName(p.name)).catch(console.error);
  }, [projectId]);

  useEffect(loadProjectName, [loadProjectName]);

  // Refetch when project metadata changes (e.g. name edited in settings modal)
  useEffect(() => {
    return subscribe("project_list_changed", loadProjectName);
  }, [loadProjectName]);

  // Running runs from WebSocket
  useEffect(() => {
    if (!projectId) return;
    return subscribe("experiment_list", (msg) => {
      const running = (msg.experiments as Experiment[])
        .filter((e) => e.status === "running" && e.project_id === projectId)
        .map(experimentToRun);
      setRunningRuns(running);
      setCompletedRefreshKey((k) => k + 1);
    });
  }, [projectId]);

  // Filters
  const bounds = useMemo(() => computeDataBounds([...runningRuns, ...completedRuns]), [runningRuns, completedRuns]);
  const [filters, setFilters] = useState<Filters>(() => emptyFilters());
  const filterKey = useMemo(() => serializeFilters(filters), [filters]);

  // Selection (completed runs only)
  const [actionsOpen, setActionsOpen] = useState(false);
  const actionsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!actionsOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (actionsRef.current && !actionsRef.current.contains(e.target as Node)) setActionsOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [actionsOpen]);

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

  // Debounce text filter changes
  const prevTextRef = useRef({ name: "", sessionId: "" });

  // Fetch completed experiments on filter/sort/page change or WebSocket refresh signal
  useEffect(() => {
    if (!projectId) return;
    const prev = prevTextRef.current;
    const textChanged = prev.name !== filters.name.value || prev.sessionId !== filters.sessionId;
    prevTextRef.current = { name: filters.name.value, sessionId: filters.sessionId };

    const controller = new AbortController();
    const delay = textChanged ? 300 : 0;

    const params: ExperimentQueryParams = {
      limit: completedRowsPerPage,
      offset: (completedPage - 1) * completedRowsPerPage,
    };
    if (completedSort) {
      params.sort = completedSort.key;
      params.dir = completedSort.direction;
    }
    if (filters.name.value) params.name = filters.name.value;
    if (filters.sessionId) params.session_id = filters.sessionId;
    if (filters.success.size > 0) params.success = Array.from(filters.success);
    if (filters.version.size > 0) params.version = Array.from(filters.version);
    if (filters.startTime.from) params.time_from = filters.startTime.from;
    if (filters.startTime.to) params.time_to = filters.startTime.to;

    const timer = setTimeout(async () => {
      try {
        const resp = await fetchProjectExperiments(projectId, params, controller.signal);
        setRunningRuns(resp.running.map(experimentToRun));
        setCompletedRuns(resp.finished.map(experimentToRun));
        setCompletedTotal(resp.finished_total);
        setDistinctVersions(resp.distinct_versions);
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        console.error("Failed to fetch experiments:", err);
      } finally {
        setLoading(false);
      }
    }, delay);

    return () => { clearTimeout(timer); controller.abort(); };
  }, [projectId, completedPage, completedRowsPerPage, completedSort, filters, completedRefreshKey]);

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
  const sortedRunning = useMemo(() => sortRuns(allRunning, runningSort), [allRunning, runningSort]);
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

  useEffect(() => {
    setActionsOpen(false);
  }, [projectId, filterKey]);

  useEffect(() => {
    if (selectedCompleted.size === 0) {
      setActionsOpen(false);
    }
  }, [selectedCompleted]);

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
        {/* Running runs section — spans full grid width */}
        <div className="runs-section running-runs-section">
          <div className="landing-section-title">
            <span className="loading-dot" />
            Running ({allRunning.length})
          </div>
          <div className="runs-section-scroll">
            <table className="runs-table">
              <thead>
                <tr>
                  <SortableHeader label="Start Time" sortKey="timestamp" sort={runningSort} onSort={handleRunningSort} />
                  <SortableHeader label="Session ID" sortKey="sessionId" sort={runningSort} onSort={handleRunningSort} />
                  <SortableHeader label="Name" sortKey="name" sort={runningSort} onSort={handleRunningSort} />
                  <SortableHeader label="Input" sortKey="input" sort={runningSort} onSort={handleRunningSort} />
                  <SortableHeader label="Version" sortKey="codeVersion" sort={runningSort} onSort={handleRunningSort} />
                  <SortableHeader label="Latency" sortKey="latency" sort={runningSort} onSort={handleRunningSort} />
                </tr>
              </thead>
              <tbody>
                {running.map((run) => (
                  <tr
                    key={run.id}
                    className="clickable-row"
                    onClick={() => navigate(`/project/${projectId}/run/${run.sessionId}`)}
                    onKeyDown={(event) => handleRowKeyDown(event, run.sessionId)}
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
            rowsPerPage={runningRowsPerPage}
            setRowsPerPage={setRunningRowsPerPage}
            currentPage={safeRunningPage}
            setCurrentPage={setRunningPage}
            totalPages={runningTotalPages}
          />
        </div>

        {/* Completed runs section */}
        <div className="runs-section completed-runs-section">
          <CompletedRunsToolbar
            actionsOpen={actionsOpen}
            actionsRef={actionsRef}
            completedTotal={completedTotal}
            hiddenSelectedCount={hiddenSelectedCount}
            onAskSovara={() => {
              setActionsOpen(false);
              navigate(`/project/${projectId}/sovara`);
            }}
            onClearSelection={clearCompletedSelection}
            onDeleteSelected={() => {
              setActionsOpen(false);
            }}
            onOpenSelectedRuns={() => {
              const ids = Array.from(selectedCompleted).join(",");
              setActionsOpen(false);
              navigate(`/project/${projectId}/run/${ids}`);
            }}
            onToggleActions={() => {
              if (selectedCompletedCount > 0) setActionsOpen(!actionsOpen);
            }}
            selectedCount={selectedCompletedCount}
          />
          <div className="runs-section-scroll">
            <CompletedRunsTable
              allVisibleSelected={allVisibleSelected}
              formatTimestamp={formatTimestamp}
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
        <FilterPanel filters={filters} setFilters={handleSetFilters} distinctVersions={distinctVersions} bounds={bounds} />
      </div>
    </div>
  );
}
