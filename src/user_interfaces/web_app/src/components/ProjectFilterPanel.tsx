import { useMemo, useState } from "react";
import { Search, X, ChevronDown as ChevronDownIcon } from "lucide-react";
import { emptyFilters, type DataBounds, type DateRangeFilter, type Filters, type RangeFilter, type TextFilter } from "../projectFilters";

function rangeActive(range: RangeFilter, bounds: { min: number; max: number }): boolean {
  return range.min > bounds.min || range.max < bounds.max;
}

function dateRangeActive(range: DateRangeFilter): boolean {
  return range.from !== "" || range.to !== "";
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
  const isInvalid = filter.isRegex && filter.value.length > 0 && (() => {
    try {
      new RegExp(filter.value);
      return false;
    } catch {
      return true;
    }
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
              onChange={(event) => onChange({ ...filter, value: event.target.value })}
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
              onChange={(event) => onChange({ ...filter, isRegex: event.target.checked })}
            />
            <span className="filter-regex-label">Regex</span>
          </label>
        </div>
      )}
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
      {open && (
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
  onChange: (selected: Set<string>) => void;
  counts?: Record<string, number>;
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
      {open && (
        <div className="filter-section-body">
          {visibleOptions.map((option) => (
            <label key={option.value} className="filter-checkbox-row">
              <input
                type="checkbox"
                checked={selected.has(option.value)}
                onChange={() => toggle(option.value)}
              />
              <span className="filter-checkbox-label">{option.label}</span>
              {counts && counts[option.value] !== undefined && (
                <span className="filter-checkbox-count">{counts[option.value]}</span>
              )}
            </label>
          ))}
          {hasMore && (
            <button className="filter-load-more-btn" onClick={() => setShowAll(!showAll)}>
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
      {open && (
        <div className="filter-section-body">
          <div className="filter-range-inputs">
            <div className="filter-range-field">
              <span className="filter-range-label">From</span>
              <input
                type="date"
                className="filter-date-input"
                value={range.from}
                onChange={(event) => onChange({ ...range, from: event.target.value })}
              />
            </div>
            <div className="filter-range-field">
              <span className="filter-range-label">To</span>
              <input
                type="date"
                className="filter-date-input"
                value={range.to}
                onChange={(event) => onChange({ ...range, to: event.target.value })}
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
  onChange: (range: RangeFilter) => void;
  open: boolean;
  onToggle: () => void;
}) {
  const isActive = rangeActive(range, bounds);
  const effectiveStep = step ?? 1;

  function commitMin(input: HTMLInputElement) {
    const value = parseFloat(input.value);
    if (isNaN(value)) {
      input.value = String(range.min);
      return;
    }
    const clamped = Math.max(bounds.min, Math.min(value, range.max));
    input.value = String(clamped);
    onChange({ ...range, min: clamped });
  }

  function commitMax(input: HTMLInputElement) {
    const value = parseFloat(input.value);
    if (isNaN(value)) {
      input.value = String(range.max);
      return;
    }
    const clamped = Math.min(bounds.max, Math.max(value, range.min));
    input.value = String(clamped);
    onChange({ ...range, max: clamped });
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
                  defaultValue={String(range.max)}
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
      )}
    </div>
  );
}

export function ProjectFilterPanel({
  filters,
  setFilters,
  distinctVersions,
  bounds,
}: {
  filters: Filters;
  setFilters: (filters: Filters) => void;
  distinctVersions: string[];
  bounds: DataBounds;
}) {
  const versionOptions = useMemo(() => ({
    options: distinctVersions.map((version) => ({ value: version, label: version })),
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

  const SECTION_KEYS = ["startTime", "name", "sessionId", "input", "output", "comment", "version", "success", "confidence", "latency", "cost"] as const;
  type SectionKey = typeof SECTION_KEYS[number];

  const [openSections, setOpenSections] = useState<Record<SectionKey, boolean>>(
    () => Object.fromEntries(SECTION_KEYS.map((key) => [key, false])) as Record<SectionKey, boolean>,
  );

  const toggle = (key: SectionKey) => setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  const anyOpen = SECTION_KEYS.some((key) => openSections[key]);
  const toggleAll = () => {
    const target = !anyOpen;
    setOpenSections(Object.fromEntries(SECTION_KEYS.map((key) => [key, target])) as Record<SectionKey, boolean>);
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
          open={openSections.startTime}
          onToggle={() => toggle("startTime")}
        />
        <TextFilterInput
          label="Name"
          filter={filters.name}
          onChange={(filter) => setFilters({ ...filters, name: filter })}
          open={openSections.name}
          onToggle={() => toggle("name")}
        />
        <PlainTextFilterInput
          label="Session ID"
          value={filters.sessionId}
          onChange={(value) => setFilters({ ...filters, sessionId: value })}
          open={openSections.sessionId}
          onToggle={() => toggle("sessionId")}
        />
        <TextFilterInput
          label="Input"
          filter={filters.input}
          onChange={(filter) => setFilters({ ...filters, input: filter })}
          open={openSections.input}
          onToggle={() => toggle("input")}
        />
        <TextFilterInput
          label="Output"
          filter={filters.output}
          onChange={(filter) => setFilters({ ...filters, output: filter })}
          open={openSections.output}
          onToggle={() => toggle("output")}
        />
        <TextFilterInput
          label="Comment"
          filter={filters.comment}
          onChange={(filter) => setFilters({ ...filters, comment: filter })}
          open={openSections.comment}
          onToggle={() => toggle("comment")}
        />
        <CheckboxFilterSection
          label="Version"
          options={versionOptions.options}
          selected={filters.version}
          onChange={(selected) => setFilters({ ...filters, version: selected })}
          open={openSections.version}
          onToggle={() => toggle("version")}
        />
        <RangeFilterSection
          label="Latency"
          range={filters.latency}
          bounds={bounds.latency}
          unit="s"
          step={0.1}
          onChange={(range) => setFilters({ ...filters, latency: range })}
          open={openSections.latency}
          onToggle={() => toggle("latency")}
        />
        <RangeFilterSection
          label="Cost"
          range={filters.cost}
          bounds={bounds.cost}
          unit="$"
          step={0.01}
          onChange={(range) => setFilters({ ...filters, cost: range })}
          open={openSections.cost}
          onToggle={() => toggle("cost")}
        />
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
            onChange={(selected) => setFilters({ ...filters, success: selected })}
            open={openSections.success}
            onToggle={() => toggle("success")}
          />
          <RangeFilterSection
            label="Confidence"
            range={filters.confidence}
            bounds={bounds.confidence}
            unit="%"
            step={1}
            onChange={(range) => setFilters({ ...filters, confidence: range })}
            open={openSections.confidence}
            onToggle={() => toggle("confidence")}
          />
        </div>
      </div>
    </div>
  );
}
