import { useMemo, useState } from "react";
import { ChevronDown as ChevronDownIcon, Search, X } from "lucide-react";

import type { CustomMetricColumn } from "../api";
import {
  emptyFilters,
  isMetricFilterActive,
  type DataBounds,
  type DateRangeFilter,
  type Filters,
  type RangeFilter,
  type TextFilter,
} from "../projectFilters";
import type { Tag } from "../tags";

function rangeActive(range: RangeFilter, bounds: { min: number; max: number }): boolean {
  return range.min > bounds.min || range.max < bounds.max;
}

function dateRangeActive(range: DateRangeFilter): boolean {
  return range.from !== "" || range.to !== "";
}

function roundToDecimals(value: number, decimals: number): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

function formatRangeValue(value: number, precision?: number): string {
  if (precision === undefined) return String(value);
  return value.toFixed(precision);
}

function TextFilterInput({
  label,
  filter,
  onChange,
  open,
  onToggle,
}: {
  label: string;
  filter: TextFilter;
  onChange: (filter: TextFilter) => void;
  open: boolean;
  onToggle: () => void;
}) {
  const hasValue = filter.value.length > 0;

  return (
    <div className={`filter-section${open ? " open" : ""}`}>
      <button className="filter-section-header" onClick={onToggle}>
        <span className="filter-label">
          {label}
          {hasValue && <span className="filter-active-dot" />}
        </span>
        <ChevronDownIcon size={12} className={`filter-chevron${open ? " rotated" : ""}`} />
      </button>
      <div className="filter-section-content">
        <div className="filter-section-body">
          <div className="filter-text-input-row">
            <Search size={12} className="filter-search-icon" />
            <input
              type="text"
              className="filter-text-input"
              placeholder={filter.isRegex ? "Regex pattern..." : "Contains..."}
              value={filter.value}
              onChange={(event) => onChange({ ...filter, value: event.target.value })}
            />
            {hasValue && (
              <button className="filter-clear-btn" onClick={() => onChange({ ...filter, value: "" })}>
                <X size={10} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function PlainTextFilterInput({
  label,
  value,
  onChange,
  open,
  onToggle,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
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
      <div className="filter-section-content">
        <div className="filter-section-body">
          <div className="filter-text-input-row">
            <Search size={12} className="filter-search-icon" />
            <input
              type="text"
              className="filter-text-input"
              placeholder="Contains..."
              value={value}
              onChange={(event) => onChange(event.target.value)}
            />
            {hasValue && (
              <button className="filter-clear-btn" onClick={() => onChange("")}>
                <X size={10} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

const CHECKBOX_INITIAL_SHOW = 5;

function CheckboxFilterSection({
  label,
  options,
  selected,
  onChange,
  open,
  onToggle,
}: {
  label: string;
  options: { value: string; label: string }[];
  selected: Set<string>;
  onChange: (selected: Set<string>) => void;
  open: boolean;
  onToggle: () => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const hasSelection = selected.size > 0;
  const hasMore = options.length > CHECKBOX_INITIAL_SHOW;
  const visibleOptions = showAll || !hasMore ? options : options.slice(0, CHECKBOX_INITIAL_SHOW);

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
      <div className="filter-section-content">
        <div className="filter-section-body">
          {visibleOptions.map((option) => (
            <label key={option.value} className="filter-checkbox-row">
              <input
                type="checkbox"
                checked={selected.has(option.value)}
                onChange={() => toggle(option.value)}
              />
              <span className="filter-checkbox-label">{option.label}</span>
            </label>
          ))}
          {hasMore && (
            <button className="filter-load-more-btn" onClick={() => setShowAll(!showAll)}>
              {showAll ? "Show less" : `Show ${options.length - CHECKBOX_INITIAL_SHOW} more`}
            </button>
          )}
        </div>
      </div>
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
  onChange: (range: DateRangeFilter) => void;
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
      <div className="filter-section-content">
        <div className="filter-section-body">
          <div className="filter-range-inputs">
            <div className="filter-range-field">
              <span className="filter-range-label">From</span>
              <input
                type="datetime-local"
                className="filter-date-input"
                value={range.from}
                step={60}
                onChange={(event) => onChange({ ...range, from: event.target.value })}
              />
            </div>
            <div className="filter-range-field">
              <span className="filter-range-label">To</span>
              <input
                type="datetime-local"
                className="filter-date-input"
                value={range.to}
                step={60}
                onChange={(event) => onChange({ ...range, to: event.target.value })}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function RangeFilterSection({
  label,
  range,
  bounds,
  unit,
  precision,
  step,
  onChange,
  open,
  onToggle,
}: {
  label: string;
  range: RangeFilter;
  bounds: { min: number; max: number };
  unit: string;
  precision?: number;
  step?: number;
  onChange: (range: RangeFilter) => void;
  open: boolean;
  onToggle: () => void;
}) {
  const isActive = rangeActive(range, bounds);
  const effectiveStep = step ?? 1;

  function commitMin(input: HTMLInputElement) {
    const value = parseFloat(input.value);
    if (isNaN(value)) {
      input.value = formatRangeValue(range.min, precision);
      return;
    }
    const clamped = Math.max(bounds.min, Math.min(value, range.max));
    const normalized = precision === undefined ? clamped : roundToDecimals(clamped, precision);
    input.value = formatRangeValue(normalized, precision);
    onChange({ ...range, min: normalized });
  }

  function commitMax(input: HTMLInputElement) {
    const value = parseFloat(input.value);
    if (isNaN(value)) {
      input.value = formatRangeValue(range.max, precision);
      return;
    }
    const clamped = Math.min(bounds.max, Math.max(value, range.min));
    const normalized = precision === undefined ? clamped : roundToDecimals(clamped, precision);
    input.value = formatRangeValue(normalized, precision);
    onChange({ ...range, max: normalized });
  }

  const minPercent = bounds.max > bounds.min ? ((range.min - bounds.min) / (bounds.max - bounds.min)) * 100 : 0;
  const maxPercent = bounds.max > bounds.min ? ((range.max - bounds.min) / (bounds.max - bounds.min)) * 100 : 100;

  return (
    <div className={`filter-section${open ? " open" : ""}`}>
      <button className="filter-section-header" onClick={onToggle}>
        <span className="filter-label">
          {label}
          {isActive && <span className="filter-active-dot" />}
        </span>
        <ChevronDownIcon size={12} className={`filter-chevron${open ? " rotated" : ""}`} />
      </button>
      <div className="filter-section-content">
        <div className="filter-section-body">
          <div className="filter-range-inputs">
            <div className="filter-range-field">
              <span className="filter-range-label">Min.</span>
              <div className="filter-range-input-wrap">
                <input
                  key={`min-${range.min}-${range.max}`}
                  type="text"
                  className="filter-range-input"
                  defaultValue={formatRangeValue(range.min, precision)}
                  onBlur={(event) => commitMin(event.currentTarget)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      commitMin(event.currentTarget);
                      event.currentTarget.blur();
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
                  defaultValue={formatRangeValue(range.max, precision)}
                  onBlur={(event) => commitMax(event.currentTarget)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      commitMax(event.currentTarget);
                      event.currentTarget.blur();
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
              style={{ left: `${minPercent}%`, right: `${100 - maxPercent}%` }}
            />
            <input
              type="range"
              className="filter-range-thumb filter-range-thumb-min"
              min={bounds.min}
              max={bounds.max}
              step={effectiveStep}
              value={range.min}
              onChange={(event) => {
                const value = parseFloat(event.target.value);
                if (value <= range.max) onChange({ ...range, min: value });
              }}
            />
            <input
              type="range"
              className="filter-range-thumb filter-range-thumb-max"
              min={bounds.min}
              max={bounds.max}
              step={effectiveStep}
              value={range.max}
              onChange={(event) => {
                const value = parseFloat(event.target.value);
                if (value >= range.min) onChange({ ...range, max: value });
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export function ProjectFilterPanel({
  bounds,
  distinctVersions,
  formatCodeVersion,
  filters,
  metricColumns,
  projectTags,
  setFilters,
}: {
  bounds: DataBounds;
  distinctVersions: string[];
  formatCodeVersion: (raw: string) => string;
  filters: Filters;
  metricColumns: CustomMetricColumn[];
  projectTags: Tag[];
  setFilters: (filters: Filters) => void;
}) {
  const versionOptions = useMemo(
    () => distinctVersions.map((version) => ({ value: version, label: formatCodeVersion(version) })),
    [distinctVersions, formatCodeVersion],
  );
  const tagOptions = useMemo(
    () => projectTags.map((tag) => ({ value: tag.tag_id, label: tag.name })),
    [projectTags],
  );
  const activeCount = [
    filters.name.value,
    filters.runId,
  ].filter(Boolean).length
    + (filters.version.size > 0 ? 1 : 0)
    + (filters.tags.size > 0 ? 1 : 0)
    + (filters.label.size > 0 ? 1 : 0)
    + (rangeActive(filters.latency, bounds.latency) ? 1 : 0)
    + (dateRangeActive(filters.startTime) ? 1 : 0)
    + Object.values(filters.customMetrics).filter((value) => isMetricFilterActive(value)).length;

  const sectionKeys = useMemo(
    () => [
      "startTime",
      "name",
      "runId",
      "version",
      "tags",
      "label",
      "latency",
      ...metricColumns.map((column) => `metric:${column.key}`),
    ],
    [metricColumns],
  );
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({});
  const toggle = (key: string) => setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  const anyOpen = sectionKeys.some((key) => openSections[key]);
  const toggleAll = () => {
    const target = !anyOpen;
    setOpenSections(Object.fromEntries(sectionKeys.map((key) => [key, target])));
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
          onChange={(range) => setFilters({ ...filters, startTime: range })}
          open={!!openSections.startTime}
          onToggle={() => toggle("startTime")}
        />
        <TextFilterInput
          label="Name"
          filter={filters.name}
          onChange={(filter) => setFilters({ ...filters, name: filter })}
          open={!!openSections.name}
          onToggle={() => toggle("name")}
        />
        <PlainTextFilterInput
          label="Run ID"
          value={filters.runId}
          onChange={(value) => setFilters({ ...filters, runId: value })}
          open={!!openSections.runId}
          onToggle={() => toggle("runId")}
        />
        <CheckboxFilterSection
          label="Version"
          options={versionOptions}
          selected={filters.version}
          onChange={(selected) => setFilters({ ...filters, version: selected })}
          open={!!openSections.version}
          onToggle={() => toggle("version")}
        />
        <CheckboxFilterSection
          label="Tags"
          options={tagOptions}
          selected={filters.tags}
          onChange={(selected) => setFilters({ ...filters, tags: selected })}
          open={!!openSections.tags}
          onToggle={() => toggle("tags")}
        />
        <CheckboxFilterSection
          label="Label"
          options={[
            { value: "up", label: "Thumbs up" },
            { value: "down", label: "Thumbs down" },
            { value: "none", label: "No label" },
          ]}
          selected={filters.label}
          onChange={(selected) => setFilters({ ...filters, label: selected })}
          open={!!openSections.label}
          onToggle={() => toggle("label")}
        />
        <RangeFilterSection
          label="Latency"
          range={filters.latency}
          bounds={bounds.latency}
          unit="s"
          step={0.1}
          onChange={(range) => setFilters({ ...filters, latency: range })}
          open={!!openSections.latency}
          onToggle={() => toggle("latency")}
        />
        {metricColumns.length > 0 && <div className="filter-group"><div className="filter-group-label">Custom Metrics</div></div>}
        {metricColumns.map((column) => {
          const sectionKey = `metric:${column.key}`;
          const currentFilter = filters.customMetrics[column.key];

          if (column.kind === "bool") {
            const selected = currentFilter?.kind === "bool" ? currentFilter.values : new Set<string>();
            return (
              <CheckboxFilterSection
                key={column.key}
                label={column.key}
                options={[
                  { value: "true", label: "True" },
                  { value: "false", label: "False" },
                ]}
                selected={selected}
                onChange={(selectedValues) => setFilters({
                  ...filters,
                  customMetrics: {
                    ...filters.customMetrics,
                    [column.key]: { kind: "bool", values: selectedValues },
                  },
                })}
                open={!!openSections[sectionKey]}
                onToggle={() => toggle(sectionKey)}
              />
            );
          }

          const boundsForColumn = {
            min: column.kind === "float" ? roundToDecimals(column.min ?? 0, 2) : (column.min ?? 0),
            max: column.kind === "float" ? roundToDecimals(column.max ?? 0, 2) : (column.max ?? 0),
          };
          const numericKind = column.kind === "int" ? "int" : "float";
          const precision = column.kind === "float" ? 2 : undefined;
          const range = currentFilter?.kind === column.kind
            ? {
                min: precision === undefined
                  ? (currentFilter.min ?? boundsForColumn.min)
                  : roundToDecimals(currentFilter.min ?? boundsForColumn.min, precision),
                max: precision === undefined
                  ? (currentFilter.max ?? boundsForColumn.max)
                  : roundToDecimals(currentFilter.max ?? boundsForColumn.max, precision),
              }
            : boundsForColumn;

          return (
            <RangeFilterSection
              key={column.key}
              label={column.key}
              range={range}
              bounds={boundsForColumn}
              unit=""
              precision={precision}
              step={column.kind === "int" ? 1 : 0.01}
              onChange={(nextRange) => {
                const nextFilters = { ...filters.customMetrics };
                const usesDefaultBounds = nextRange.min <= boundsForColumn.min && nextRange.max >= boundsForColumn.max;
                if (usesDefaultBounds) {
                  delete nextFilters[column.key];
                } else {
                  nextFilters[column.key] = {
                    kind: numericKind,
                    min: precision === undefined ? nextRange.min : roundToDecimals(nextRange.min, precision),
                    max: precision === undefined ? nextRange.max : roundToDecimals(nextRange.max, precision),
                  };
                }
                setFilters({ ...filters, customMetrics: nextFilters });
              }}
              open={!!openSections[sectionKey]}
              onToggle={() => toggle(sectionKey)}
            />
          );
        })}
      </div>
    </div>
  );
}
