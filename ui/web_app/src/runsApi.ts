import { get, post } from "./api";
import type { Tag } from "./tags";

export interface Run {
  run_id: string;
  status: "running" | "finished";
  timestamp: string;
  runtime_seconds: number | null;
  active_runtime_seconds: number | null;
  color_preview: string[];
  version_date: string | null;
  name: string;
  custom_metrics: Record<string, boolean | number>;
  thumb_label: boolean | null;
  tags: Tag[];
  project_id?: string | null;
}

export interface RunQueryParams {
  limit?: number;
  offset?: number;
  sort?: string;
  dir?: string;
  name?: string;
  run_id?: string;
  label?: string[];
  tag_id?: string[];
  version?: string[];
  metric_filters?: Record<string, MetricFilter>;
  time_from?: string;
  time_to?: string;
  latency_min?: number;
  latency_max?: number;
}

export type MetricKind = "bool" | "int" | "float";
export type MetricFilter =
  | { kind: "bool"; values: boolean[] }
  | { kind: "int" | "float"; min?: number; max?: number };

export interface CustomMetricColumn {
  key: string;
  kind: MetricKind;
  min?: number;
  max?: number;
  values?: boolean[];
}

interface ProjectRunsResponse {
  type: string;
  running: Run[];
  finished: Run[];
  finished_total: number;
  distinct_versions: string[];
  custom_metric_columns: CustomMetricColumn[];
}

export async function fetchProjectRuns(
  projectId: string,
  params?: RunQueryParams,
  signal?: AbortSignal,
): Promise<ProjectRunsResponse> {
  const qs = new URLSearchParams();
  if (params) {
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    if (params.offset !== undefined) qs.set("offset", String(params.offset));
    if (params.sort) qs.set("sort", params.sort);
    if (params.dir) qs.set("dir", params.dir);
    if (params.name) qs.set("name", params.name);
    if (params.run_id) qs.set("run_id", params.run_id);
    if (params.time_from) qs.set("time_from", params.time_from);
    if (params.time_to) qs.set("time_to", params.time_to);
    if (params.latency_min !== undefined) qs.set("latency_min", String(params.latency_min));
    if (params.latency_max !== undefined) qs.set("latency_max", String(params.latency_max));
    if (params.label) for (const value of params.label) qs.append("label", value);
    if (params.tag_id) for (const value of params.tag_id) qs.append("tag_id", value);
    if (params.version) for (const value of params.version) qs.append("version", value);
    if (params.metric_filters && Object.keys(params.metric_filters).length > 0) {
      qs.set("metric_filters", JSON.stringify(params.metric_filters));
    }
  }
  const query = qs.toString();
  const url = `/ui/projects/${projectId}/runs${query ? `?${query}` : ""}`;
  return get<ProjectRunsResponse>(url, { signal });
}

export interface RunDetail {
  run_id: string;
  name: string;
  timestamp: string;
  runtime_seconds: number | null;
  active_runtime_seconds: number | null;
  custom_metrics: Record<string, boolean | number>;
  thumb_label: boolean | null;
  tags: Tag[];
  notes: string;
  log: string;
  version_date: string | null;
  status: "running" | "finished";
}

export async function fetchRunDetail(runId: string): Promise<RunDetail> {
  return get(`/ui/run/${runId}`);
}

export interface BackendGraphNode {
  uuid: string;
  step_id: number;
  input: string;
  output: string;
  label: string;
  border_color?: string;
  stack_trace?: string;
  name?: string;
  attachments?: unknown[];
}

export interface BackendGraphEdge {
  id: string;
  source_uuid: string;
  target_uuid: string;
}

export interface GraphPayload {
  nodes: BackendGraphNode[];
  edges: BackendGraphEdge[];
}

export interface GraphResponse {
  type: string;
  run_id: string;
  payload: GraphPayload;
  active_runtime_seconds?: number | null;
}

export async function fetchGraph(runId: string): Promise<GraphResponse> {
  return get<GraphResponse>(`/ui/graph/${runId}`);
}

export async function editInput(runId: string, nodeId: string, value: string): Promise<void> {
  await post("/ui/edit-input", { run_id: runId, node_uuid: nodeId, value });
}

export async function editOutput(runId: string, nodeId: string, value: string): Promise<void> {
  await post("/ui/edit-output", { run_id: runId, node_uuid: nodeId, value });
}

export async function restartRun(runId: string): Promise<void> {
  await post("/ui/restart", { run_id: runId });
}

export async function eraseRun(runId: string): Promise<void> {
  await post("/ui/erase", { run_id: runId });
}

export async function updateThumbLabel(runId: string, thumbLabel: boolean | null): Promise<void> {
  await post("/ui/update-thumb-label", { run_id: runId, thumb_label: thumbLabel });
}

export async function updateRunName(runId: string, runName: string): Promise<void> {
  await post("/ui/update-run-name", { run_id: runId, name: runName });
}

export async function updateRunTags(runId: string, tagIds: string[]): Promise<Tag[]> {
  const data = await post<{ tags: Tag[] }>("/ui/update-run-tags", { run_id: runId, tag_ids: tagIds });
  return data.tags;
}

export async function deleteRuns(runIds: string[]): Promise<{ deleted: number }> {
  return post("/ui/delete-runs", {
    run_ids: runIds,
  });
}
