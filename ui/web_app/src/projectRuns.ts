import type { Experiment } from "./api";
import type { SortState } from "./hooks/useStoredSortState";
import type { Tag } from "./tags";

export interface ProjectRun {
  id: string;
  sessionId: string;
  name: string;
  status: "running" | "finished";
  timestamp: string;
  latency: string;
  latencySeconds: number | null;
  activeRuntimeSeconds: number | null;
  codeVersion: string;
  thumbLabel: boolean | null;
  customMetrics: Record<string, boolean | number>;
  tags: Tag[];
}

function normalizeRuntimeSeconds(value: number | null | undefined): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.max(0, value);
}

export function formatRuntimeSeconds(value: number | null | undefined): string {
  const normalized = normalizeRuntimeSeconds(value);
  if (normalized === null) return "—";
  return `${normalized.toFixed(1)}s`;
}

export function experimentToProjectRun(experiment: Experiment): ProjectRun {
  const activeRuntimeSeconds = normalizeRuntimeSeconds(experiment.active_runtime_seconds);
  const latencySeconds = experiment.status === "running"
    ? activeRuntimeSeconds
    : normalizeRuntimeSeconds(experiment.runtime_seconds) ?? activeRuntimeSeconds;
  return {
    id: experiment.session_id,
    sessionId: experiment.session_id,
    name: experiment.run_name,
    status: experiment.status === "running" ? "running" : "finished",
    timestamp: experiment.timestamp,
    codeVersion: experiment.version_date ?? "—",
    thumbLabel: experiment.thumb_label,
    customMetrics: experiment.custom_metrics ?? {},
    latency: formatRuntimeSeconds(latencySeconds),
    latencySeconds,
    activeRuntimeSeconds,
    tags: experiment.tags ?? [],
  };
}

export function parseProjectRunTimestamp(raw: string): number {
  const normalized = raw.replace(" ", "T");
  return new Date(normalized.endsWith("Z") ? normalized : `${normalized}Z`).getTime();
}

export function formatProjectRunTimestamp(raw: string): string {
  if (!raw) return "—";
  const milliseconds = parseProjectRunTimestamp(raw);
  if (isNaN(milliseconds)) return raw;
  return new Date(milliseconds).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    hourCycle: "h23",
  });
}

function compareProjectRuns(a: ProjectRun, b: ProjectRun, key: string): number {
  switch (key) {
    case "timestamp":
      return a.timestamp.localeCompare(b.timestamp);
    case "sessionId":
      return a.sessionId.localeCompare(b.sessionId);
    case "name": {
      const numberA = parseInt(a.name.replace(/^Run\s*/, ""), 10);
      const numberB = parseInt(b.name.replace(/^Run\s*/, ""), 10);
      if (!isNaN(numberA) && !isNaN(numberB)) return numberA - numberB;
      return a.name.localeCompare(b.name);
    }
    case "codeVersion":
      return a.codeVersion.localeCompare(b.codeVersion);
    case "latency":
      return (a.latencySeconds ?? Infinity) - (b.latencySeconds ?? Infinity);
    case "thumbLabel": {
      const valueA = a.thumbLabel === null ? -1 : a.thumbLabel ? 1 : 0;
      const valueB = b.thumbLabel === null ? -1 : b.thumbLabel ? 1 : 0;
      return valueA - valueB;
    }
    case "tags":
      return a.tags.map((tag) => tag.name).join(",").localeCompare(b.tags.map((tag) => tag.name).join(","));
    default:
      return 0;
  }
}

export function sortProjectRuns(runs: ProjectRun[], sort: SortState): ProjectRun[] {
  if (!sort) return runs;
  const sorted = [...runs].sort((a, b) => compareProjectRuns(a, b, sort.key));
  return sort.direction === "desc" ? sorted.reverse() : sorted;
}
