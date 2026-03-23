import type { Experiment } from "./api";
import type { SortState } from "./hooks/useStoredSortState";

export interface ProjectRun {
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

export function experimentToProjectRun(experiment: Experiment): ProjectRun {
  return {
    id: experiment.session_id,
    sessionId: experiment.session_id,
    name: experiment.run_name,
    status: experiment.status === "running" ? "running" : "finished",
    timestamp: experiment.timestamp,
    codeVersion: experiment.version_date ?? "—",
    success: experiment.result === "Satisfactory" ? true : experiment.result === "Failed" ? false : null,
    input: "—",
    output: "—",
    latency: "—",
    cost: "—",
    confidence: null,
    tags: [],
    comment: "—",
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
  });
}

function parseLatency(value: string): number {
  const parsed = parseFloat(value);
  return isNaN(parsed) ? Infinity : parsed;
}

function parseCost(value: string): number {
  const parsed = parseFloat(value.replace(/[^0-9.]/g, ""));
  return isNaN(parsed) ? Infinity : parsed;
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
    case "input":
      return a.input.localeCompare(b.input);
    case "output":
      return (a.output || "").localeCompare(b.output || "");
    case "codeVersion":
      return a.codeVersion.localeCompare(b.codeVersion);
    case "latency":
      return parseLatency(a.latency) - parseLatency(b.latency);
    case "success": {
      const valueA = a.success === null ? -1 : a.success ? 1 : 0;
      const valueB = b.success === null ? -1 : b.success ? 1 : 0;
      return valueA - valueB;
    }
    case "confidence":
      return (a.confidence ?? -1) - (b.confidence ?? -1);
    case "cost":
      return parseCost(a.cost) - parseCost(b.cost);
    case "tags":
      return a.tags.join(",").localeCompare(b.tags.join(","));
    case "comment":
      return a.comment.localeCompare(b.comment);
    default:
      return 0;
  }
}

export function sortProjectRuns(runs: ProjectRun[], sort: SortState): ProjectRun[] {
  if (!sort) return runs;
  const sorted = [...runs].sort((a, b) => compareProjectRuns(a, b, sort.key));
  return sort.direction === "desc" ? sorted.reverse() : sorted;
}
