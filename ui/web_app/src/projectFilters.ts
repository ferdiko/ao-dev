import type { MetricFilter } from "./runsApi";

export interface TextFilter {
  value: string;
  isRegex: boolean;
}

export interface RangeFilter {
  min: number;
  max: number;
  enabled?: boolean;
}

export interface DateRangeFilter {
  from: string;
  to: string;
}

export interface BoolMetricFilterState {
  kind: "bool";
  values: Set<string>;
}

export interface NumberMetricFilterState {
  kind: "int" | "float";
  min: number | null;
  max: number | null;
}

export type MetricFilterState = BoolMetricFilterState | NumberMetricFilterState;

export interface Filters {
  name: TextFilter;
  runId: string;
  version: Set<string>;
  tags: Set<string>;
  label: Set<string>;
  customMetrics: Record<string, MetricFilterState>;
  latency: RangeFilter;
  startTime: DateRangeFilter;
}

export interface DataBounds {
  latency: { min: number; max: number };
}

function padNumber(value: number): string {
  return String(value).padStart(2, "0");
}

function parseLatencyValue(value: string): number {
  const parsed = parseFloat(value);
  return isNaN(parsed) ? 0 : parsed;
}

export function computeDataBounds(runs: Array<{ latency: string }>): DataBounds {
  let latencyMin = Infinity;
  let latencyMax = -Infinity;

  for (const run of runs) {
    const latency = parseLatencyValue(run.latency);
    if (latency > 0) {
      latencyMin = Math.min(latencyMin, latency);
      latencyMax = Math.max(latencyMax, latency);
    }
  }

  return {
    latency: {
      min: latencyMin === Infinity ? 0 : Math.floor(latencyMin),
      max: latencyMax === -Infinity ? 100 : Math.ceil(latencyMax),
    },
  };
}

export function emptyFilters(bounds?: DataBounds): Filters {
  return {
    name: { value: "", isRegex: false },
    runId: "",
    version: new Set(),
    tags: new Set(),
    label: new Set(),
    customMetrics: {},
    latency: bounds ? { ...bounds.latency, enabled: false } : { min: 0, max: 100, enabled: false },
    startTime: { from: "", to: "" },
  };
}

export function isMetricFilterActive(filter: MetricFilterState): boolean {
  if (filter.kind === "bool") {
    return filter.values.size > 0;
  }
  return filter.min !== null || filter.max !== null;
}

export function isRangeFilterActive(filter: RangeFilter): boolean {
  return Boolean(filter.enabled);
}

export function serializeFilters(filters: Filters): string {
  const serializedMetricFilters = Object.fromEntries(
    Object.entries(filters.customMetrics)
      .sort(([keyA], [keyB]) => keyA.localeCompare(keyB))
      .map(([key, value]) => {
        if (value.kind === "bool") {
          return [key, { kind: value.kind, values: Array.from(value.values).sort() }];
        }
        return [key, { kind: value.kind, min: value.min, max: value.max }];
      }),
  );

  return JSON.stringify({
    name: filters.name,
    runId: filters.runId,
    version: Array.from(filters.version).sort(),
    tags: Array.from(filters.tags).sort(),
    label: Array.from(filters.label).sort(),
    customMetrics: serializedMetricFilters,
    latency: filters.latency.enabled
      ? filters.latency
      : { enabled: false },
    startTime: filters.startTime,
  });
}

export function buildMetricFilterPayload(customMetrics: Record<string, MetricFilterState>): Record<string, MetricFilter> {
  const payload: Record<string, MetricFilter> = {};

  for (const [key, value] of Object.entries(customMetrics)) {
    if (value.kind === "bool") {
      if (value.values.size === 0) continue;
      payload[key] = {
        kind: "bool",
        values: Array.from(value.values).sort().map((item) => item === "true"),
      };
      continue;
    }

    if (value.min === null && value.max === null) continue;
    payload[key] = {
      kind: value.kind,
      min: value.min ?? undefined,
      max: value.max ?? undefined,
    };
  }

  return payload;
}

export function toUtcFilterTimestamp(rawValue: string, endOfRange = false): string {
  const value = rawValue.trim();
  if (!value) return "";

  const match = value.match(
    /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?$/,
  );
  if (!match) return value.replace("T", " ");

  const [, yearStr, monthStr, dayStr, hourStr, minuteStr, secondStr] = match;
  const hasTime = hourStr !== undefined && minuteStr !== undefined;
  const year = Number.parseInt(yearStr, 10);
  const month = Number.parseInt(monthStr, 10);
  const day = Number.parseInt(dayStr, 10);
  const hour = hasTime ? Number.parseInt(hourStr, 10) : (endOfRange ? 23 : 0);
  const minute = hasTime ? Number.parseInt(minuteStr, 10) : (endOfRange ? 59 : 0);
  const second = secondStr !== undefined
    ? Number.parseInt(secondStr, 10)
    : (endOfRange ? 59 : 0);

  const date = new Date(year, month - 1, day, hour, minute, second);
  if (Number.isNaN(date.getTime())) return value.replace("T", " ");

  return [
    `${date.getUTCFullYear()}-${padNumber(date.getUTCMonth() + 1)}-${padNumber(date.getUTCDate())}`,
    `${padNumber(date.getUTCHours())}:${padNumber(date.getUTCMinutes())}:${padNumber(date.getUTCSeconds())}`,
  ].join(" ");
}
