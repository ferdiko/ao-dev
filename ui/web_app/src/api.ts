/**
 * API layer for communicating with the sovara backend.
 *
 * All backend communication goes through this module.
 * Types use the same field names as the backend JSON responses.
 */

import type { Tag } from "./tags";

// ============================================================
// Types (match backend response shapes)
// ============================================================

export interface ProjectLocation {
  path: string;
  valid: boolean;
}

export interface Project {
  project_id: string;
  name: string;
  description: string;
  created_at: string;
  last_run_at: string | null;
  num_runs: number;
  num_users: number;
  locations: ProjectLocation[];
  location_warning: boolean;
}

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

// ============================================================
// HTTP helpers
// ============================================================

const BACKEND_START_TIMEOUT_MS = 10_000;
const BACKEND_HEALTH_POLL_MS = 250;
let backendStartupPromise: Promise<void> | null = null;

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error && error.name === "AbortError";
}

async function isBackendHealthy(): Promise<boolean> {
  try {
    const resp = await fetch("/_sovara/health");
    return resp.ok;
  } catch {
    return false;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function parseJsonResponse<T>(resp: Response, method: string, path: string): Promise<T> {
  if (!resp.ok) {
    const data = await resp.json().catch(() => null);
    throw new Error(data?.detail ?? data?.error ?? `${method} ${path} failed: ${resp.status}`);
  }
  return resp.json();
}

async function ensureBackendRunning(skipInitialHealthCheck = false): Promise<void> {
  if (!skipInitialHealthCheck && await isBackendHealthy()) {
    return;
  }

  if (!backendStartupPromise) {
    backendStartupPromise = (async () => {
      const startResp = await fetch("/_sovara/start-server", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!startResp.ok) {
        throw new Error(`POST /_sovara/start-server failed: ${startResp.status}`);
      }

      const deadline = Date.now() + BACKEND_START_TIMEOUT_MS;
      while (Date.now() < deadline) {
        if (await isBackendHealthy()) {
          return;
        }
        await sleep(BACKEND_HEALTH_POLL_MS);
      }

      throw new Error("Timed out waiting for the Sovara backend to start");
    })().finally(() => {
      backendStartupPromise = null;
    });
  }

  await backendStartupPromise;
}

async function maybeRecoverBackend(status?: number): Promise<boolean> {
  if (status !== undefined && status < 500) {
    return false;
  }
  if (await isBackendHealthy()) {
    return false;
  }
  await ensureBackendRunning(true);
  return true;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method ?? "GET";

  try {
    const resp = await fetch(path, init);
    if (!resp.ok && await maybeRecoverBackend(resp.status)) {
      return parseJsonResponse<T>(await fetch(path, init), method, path);
    }
    return parseJsonResponse<T>(resp, method, path);
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    if (await maybeRecoverBackend()) {
      return parseJsonResponse<T>(await fetch(path, init), method, path);
    }
    throw error;
  }
}

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  return requestJson<T>(path, init);
}

async function post<T>(path: string, body: unknown, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  return requestJson<T>(path, {
    ...init,
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}

export { post };

// ============================================================
// User endpoints
// ============================================================

export interface User {
  user_id: string;
  full_name: string;
  email: string;
  llm_settings: UserLlmSettings;
}

export type LlmProvider = "anthropic" | "together" | "hosted_vllm";

export interface UserLlmTierSettings {
  provider: LlmProvider;
  model_name: string;
  api_base: string | null;
}

export interface UserLlmSettings {
  primary: UserLlmTierSettings;
  helper: UserLlmTierSettings;
}

export async function fetchUser(): Promise<User | null> {
  const data = await get<{ user: User | null }>("/ui/user");
  return data.user;
}

export async function setupUser(
  fullName: string,
  email: string
): Promise<User> {
  const data = await post<{ user: User }>("/ui/setup-user", {
    full_name: fullName,
    email,
  });
  return data.user;
}

export async function updateUser(
  fullName: string,
  email: string
): Promise<User> {
  const data = await post<{ user: User }>("/ui/update-user", {
    full_name: fullName,
    email,
  });
  return data.user;
}

export async function updateUserLlmSettings(
  llmSettings: UserLlmSettings,
): Promise<User> {
  const data = await post<{ user: User }>("/ui/update-user-llm-settings", llmSettings);
  return data.user;
}

export async function deleteUser(confirmationName: string): Promise<void> {
  await post("/ui/delete-user", { confirmation_name: confirmationName });
}

// ============================================================
// Project creation
// ============================================================

export async function pickDirectory(): Promise<string | null> {
  const data = await post<{ path: string | null }>("/ui/pick-directory", {});
  return data.path;
}

export async function createProject(
  name: string,
  description: string,
  location: string
): Promise<{ project_id: string; name: string }> {
  return post("/ui/create-project", { name, description, location });
}

// ============================================================
// Project management
// ============================================================

export async function updateProjectLocation(
  projectId: string,
  oldLocation: string,
  newLocation: string
): Promise<void> {
  await post("/ui/update-project-location", {
    project_id: projectId,
    old_location: oldLocation,
    new_location: newLocation,
  });
}

export async function deleteProjectLocation(
  projectId: string,
  location: string
): Promise<void> {
  await post("/ui/delete-project-location", {
    project_id: projectId,
    location,
  });
}

export async function updateProject(
  projectId: string,
  name: string,
  description: string,
): Promise<{ project_id: string; name: string; description: string }> {
  return post("/ui/update-project", {
    project_id: projectId,
    name,
    description,
  });
}

export async function deleteProject(
  projectId: string,
  confirmationName: string
): Promise<void> {
  await post("/ui/delete-project", {
    project_id: projectId,
    confirmation_name: confirmationName,
  });
}

export async function deleteRuns(runIds: string[]): Promise<{ deleted: number }> {
  return post("/ui/delete-runs", {
    run_ids: runIds,
  });
}

// ============================================================
// Project endpoints
// ============================================================

export async function fetchProjects(): Promise<Project[]> {
  const data = await get<{ projects: Project[] }>("/ui/projects");
  return data.projects;
}

export async function fetchProject(
  projectId: string
): Promise<{ project_id: string; name: string; description: string }> {
  return get(`/ui/projects/${projectId}`);
}

// ============================================================
// Run endpoints (project-scoped)
// ============================================================

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

interface ProjectTagsResponse {
  tags: Tag[];
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
    if (params.label) for (const v of params.label) qs.append("label", v);
    if (params.tag_id) for (const v of params.tag_id) qs.append("tag_id", v);
    if (params.version) for (const v of params.version) qs.append("version", v);
    if (params.metric_filters && Object.keys(params.metric_filters).length > 0) {
      qs.set("metric_filters", JSON.stringify(params.metric_filters));
    }
  }
  const query = qs.toString();
  const url = `/ui/projects/${projectId}/runs${query ? `?${query}` : ""}`;
  return get<ProjectRunsResponse>(url, { signal });
}

export async function fetchProjectTags(projectId: string): Promise<Tag[]> {
  const data = await get<ProjectTagsResponse>(`/ui/projects/${projectId}/tags`);
  return data.tags;
}

export async function createProjectTag(projectId: string, name: string, color: string): Promise<Tag> {
  const data = await post<{ tag: Tag }>(`/ui/projects/${projectId}/tags`, { name, color });
  return data.tag;
}

export async function deleteProjectTag(projectId: string, tagId: string): Promise<void> {
  await post(`/ui/projects/${projectId}/tags/delete`, { tag_id: tagId });
}

// ============================================================
// Run detail endpoints
// ============================================================

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

export interface TraceChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface TraceChatResponse {
  history: TraceChatHistoryMessage[];
  answer?: string;
  edits_applied?: boolean;
}

export async function fetchTraceChatHistory(runId: string): Promise<TraceChatHistoryMessage[]> {
  const data = await get<{ history: TraceChatHistoryMessage[] }>(`/ui/trace-chat/${runId}`);
  return data.history;
}

export async function saveTraceChatHistory(
  runId: string,
  history: TraceChatHistoryMessage[],
): Promise<TraceChatHistoryMessage[]> {
  const data = await post<{ history: TraceChatHistoryMessage[] }>(`/ui/trace-chat/${runId}`, { history });
  return data.history;
}

export async function clearTraceChatHistory(runId: string): Promise<TraceChatHistoryMessage[]> {
  const data = await post<{ history: TraceChatHistoryMessage[] }>(`/ui/trace-chat/${runId}/clear`, {});
  return data.history;
}

// ============================================================
// Graph endpoints
// ============================================================

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

export async function fetchGraph(runId: string) {
  return get<GraphResponse>(
    `/ui/graph/${runId}`
  );
}

// ============================================================
// Run action endpoints
// ============================================================

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

export function prefetchTrace(runId: string): void {
  post(`/ui/prefetch/${runId}`, {}).catch(() => {});
}

export async function abortTraceChat(runId: string): Promise<void> {
  await post(`/ui/chat/${runId}/abort`, {});
}

export async function chatWithTrace(
  runId: string,
  message: string,
  history: { role: string; content: string }[],
  signal?: AbortSignal,
): Promise<TraceChatResponse> {
  return post(`/ui/chat/${runId}`, { message, history }, { signal });
}
