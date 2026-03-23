export interface TextFilter {
  value: string;
  isRegex: boolean;
}

export interface RangeFilter {
  min: number;
  max: number;
}

export interface DateRangeFilter {
  from: string;
  to: string;
}

export interface Filters {
  name: TextFilter;
  sessionId: string;
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

export interface DataBounds {
  latency: { min: number; max: number };
  confidence: { min: number; max: number };
  cost: { min: number; max: number };
}

function parseLatencyValue(value: string): number {
  const parsed = parseFloat(value);
  return isNaN(parsed) ? 0 : parsed;
}

function parseCostValue(value: string): number {
  const parsed = parseFloat(value.replace(/[^0-9.]/g, ""));
  return isNaN(parsed) ? 0 : parsed;
}

export function computeDataBounds(runs: Array<{ latency: string; confidence: number | null; cost: string }>): DataBounds {
  let latencyMin = Infinity;
  let latencyMax = -Infinity;
  let confidenceMin = Infinity;
  let confidenceMax = -Infinity;
  let costMin = Infinity;
  let costMax = -Infinity;

  for (const run of runs) {
    const latency = parseLatencyValue(run.latency);
    if (latency > 0) {
      latencyMin = Math.min(latencyMin, latency);
      latencyMax = Math.max(latencyMax, latency);
    }
    if (run.confidence !== null) {
      confidenceMin = Math.min(confidenceMin, run.confidence);
      confidenceMax = Math.max(confidenceMax, run.confidence);
    }
    const cost = parseCostValue(run.cost);
    if (cost > 0) {
      costMin = Math.min(costMin, cost);
      costMax = Math.max(costMax, cost);
    }
  }

  return {
    latency: {
      min: latencyMin === Infinity ? 0 : Math.floor(latencyMin),
      max: latencyMax === -Infinity ? 100 : Math.ceil(latencyMax),
    },
    confidence: {
      min: confidenceMin === Infinity ? 0 : Math.floor(confidenceMin),
      max: confidenceMax === -Infinity ? 100 : Math.ceil(confidenceMax),
    },
    cost: {
      min: costMin === Infinity ? 0 : Math.floor(costMin * 100) / 100,
      max: costMax === -Infinity ? 1 : Math.ceil(costMax * 100) / 100,
    },
  };
}

export function emptyFilters(bounds?: DataBounds): Filters {
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

export function serializeFilters(filters: Filters): string {
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
