/**
 * API layer for communicating with the sovara backend.
 *
 * All backend communication goes through this module.
 * Types use the same field names as the backend JSON responses.
 */

import type { PriorRetrievalRecord } from "@sovara/shared-components/types";
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

async function get<T>(path: string): Promise<T> {
  const resp = await fetchWithBackendRetry(path);
  if (!resp.ok) {
    throw new Error(await readErrorMessage(resp, `GET ${path} failed: ${resp.status}`));
  }
  return resp.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetchWithBackendRetry(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(await readErrorMessage(resp, `POST ${path} failed: ${resp.status}`));
  }
  return resp.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetchWithBackendRetry(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(await readErrorMessage(resp, `PUT ${path} failed: ${resp.status}`));
  }
  return resp.json();
}

async function del<T>(path: string): Promise<T> {
  const resp = await fetchWithBackendRetry(path, {
    method: "DELETE",
  });
  if (!resp.ok) {
    throw new Error(await readErrorMessage(resp, `DELETE ${path} failed: ${resp.status}`));
  }
  return resp.json();
}

export { post };

function shouldRetryBackend(resp: Response): boolean {
  return resp.status >= 500;
}

async function readErrorMessage(resp: Response, fallback: string): Promise<string> {
  try {
    const cloned = resp.clone();
    const data = await cloned.json();
    if (data && typeof data === "object") {
      const error = "error" in data ? data.error : null;
      if (typeof error === "string" && error.trim()) {
        return error;
      }
      const detail = "detail" in data ? data.detail : null;
      if (typeof detail === "string" && detail.trim()) {
        return detail;
      }
    }
  } catch {
    // Fall through to text parsing below.
  }

  try {
    const text = await resp.text();
    if (text.trim()) {
      return text.trim();
    }
  } catch {
    // Fall back to the generic status message below.
  }

  return fallback;
}

async function fetchWithBackendRetry(path: string, init?: RequestInit): Promise<Response> {
  try {
    const resp = await fetch(path, init);
    if (!shouldRetryBackend(resp)) {
      return resp;
    }
  } catch {
    // Fall through to the startup hook below.
  }

  await ensureBackendRunning();
  return fetch(path, init);
}

function withQuery(path: string, params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

async function ensureBackendRunning(): Promise<void> {
  if (await isBackendHealthy()) {
    return;
  }

  const resp = await fetch("/_sovara/start-server", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!resp.ok) {
    throw new Error(`POST /_sovara/start-server failed: ${resp.status}`);
  }

  const started = await waitForBackendHealthy();
  if (!started) {
    throw new Error("Timed out waiting for local so-server to start");
  }
}

async function isBackendHealthy(): Promise<boolean> {
  try {
    const resp = await fetch("/_sovara/health");
    return resp.ok;
  } catch {
    return false;
  }
}

async function waitForBackendHealthy(timeoutMs = 5000, intervalMs = 150): Promise<boolean> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (await isBackendHealthy()) {
      return true;
    }
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
  }
  return false;
}

export async function keepBackendAlive(): Promise<void> {
  const resp = await fetchWithBackendRetry("/health", { cache: "no-store" });
  if (!resp.ok) {
    throw new Error(`GET /health failed: ${resp.status}`);
  }
}

// ============================================================
// User endpoints
// ============================================================

export interface User {
  user_id: string;
  full_name: string;
  email: string;
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
// Priors endpoints
// ============================================================

export interface PriorRecord {
  id: string;
  name: string;
  summary: string;
  content?: string;
  path?: string;
  prior_status: "draft" | "active";
  validationSeverity?: "info" | "warning" | "error";
}

export interface PriorValidationDetail {
  feedback: string;
  severity: "info" | "warning" | "error";
  conflicting_prior_ids: string[];
}

export interface PriorMutationResponse extends PriorRecord {
  status: "created" | "updated" | "deleted" | "submitted" | "rejected";
  reason?: string;
  hint?: string;
  conflicting_prior_ids?: string[];
  validation?: PriorValidationDetail;
}

export interface FolderLsResponse {
  folders: Array<{ path: string; prior_count: number }>;
  priors: PriorRecord[];
  prior_count: number;
}

export interface FolderMutationResponse {
  status: "created" | "updated" | "deleted";
  path: string;
  new_path?: string;
}

export interface PriorItemRef {
  kind: "prior" | "folder";
  id?: string;
  path?: string;
}

export interface PriorBatchMutationResponse {
  status: "copied" | "moved" | "deleted";
  items?: Array<{
    kind: "prior" | "folder";
    id?: string;
    path?: string;
    name?: string;
  }>;
  count: number;
}

export interface PriorRunsResponse {
  type: string;
  prior_id: string;
  records: Array<{ runId: string; nodeUuid?: string; name: string }>;
}

export async function fetchPriorsFolder(projectId: string, path = ""): Promise<FolderLsResponse> {
  return post(withQuery("/ui/priors/folders/ls", { project_id: projectId }), { path });
}

export async function createPriorFolder(projectId: string, path: string): Promise<FolderMutationResponse> {
  return post(withQuery("/ui/priors/folders", { project_id: projectId }), { path });
}

export async function movePriorFolder(
  projectId: string,
  path: string,
  newPath: string,
): Promise<FolderMutationResponse> {
  return put(withQuery("/ui/priors/folders", { project_id: projectId }), { path, new_path: newPath });
}

export async function deletePriorFolder(projectId: string, path: string): Promise<FolderMutationResponse> {
  return post(withQuery("/ui/priors/folders/delete", { project_id: projectId }), { path });
}

export async function copyPriorItems(
  projectId: string,
  items: PriorItemRef[],
  destinationPath: string,
  asDraft = false,
): Promise<PriorBatchMutationResponse> {
  return post(withQuery("/ui/priors/items/copy", { project_id: projectId }), {
    items,
    destination_path: destinationPath,
    as_draft: asDraft,
  });
}

export async function movePriorItems(
  projectId: string,
  items: PriorItemRef[],
  destinationPath: string,
): Promise<PriorBatchMutationResponse> {
  return post(withQuery("/ui/priors/items/move", { project_id: projectId }), {
    items,
    destination_path: destinationPath,
  });
}

export async function deletePriorItems(
  projectId: string,
  items: PriorItemRef[],
): Promise<PriorBatchMutationResponse> {
  return post(withQuery("/ui/priors/items/delete", { project_id: projectId }), { items });
}

export async function fetchPrior(projectId: string, priorId: string): Promise<PriorRecord> {
  return get(withQuery(`/ui/priors/${priorId}`, { project_id: projectId }));
}

export async function createPrior(
  projectId: string,
  body: { name: string; summary?: string; content: string; path?: string },
  force = false,
): Promise<PriorMutationResponse> {
  return post(withQuery("/ui/priors", { project_id: projectId, force }), body);
}

export async function createDraftPrior(
  projectId: string,
  body: { name: string; content: string; path?: string },
): Promise<PriorMutationResponse> {
  return post(withQuery("/ui/priors/drafts", { project_id: projectId }), body);
}

export async function updatePrior(
  projectId: string,
  priorId: string,
  body: Partial<{ name: string; summary: string; content: string; path?: string }>,
  force = false,
): Promise<PriorMutationResponse> {
  return put(withQuery(`/ui/priors/${priorId}`, { project_id: projectId, force }), body);
}

export async function submitPrior(
  projectId: string,
  priorId: string,
  body: Partial<{ name: string; content: string; path?: string }>,
  force = false,
): Promise<PriorMutationResponse> {
  return post(withQuery(`/ui/priors/${priorId}/submit`, { project_id: projectId, force }), body);
}

export async function deletePrior(projectId: string, priorId: string): Promise<{ status: string; id: string }> {
  return del(withQuery(`/ui/priors/${priorId}`, { project_id: projectId }));
}

export async function fetchRunsForPrior(priorId: string): Promise<PriorRunsResponse> {
  return get(`/ui/runs-for-prior/${priorId}`);
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
  const resp = await fetch(url, { signal });
  if (!resp.ok) throw new Error(`GET ${url} failed: ${resp.status}`);
  return resp.json();
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
  raw_node_name?: string;
  node_kind?: string | null;
  prior_count?: number | null;
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

export async function fetchPriorRetrievals(runId: string): Promise<Record<string, PriorRetrievalRecord>> {
  const response = await get<{ type: string; run_id: string; records: PriorRetrievalRecord[] }>(
    `/ui/run/${runId}/prior-retrievals`,
  );
  return Object.fromEntries((response.records || []).map((record) => [record.node_uuid, record]));
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

export async function chatWithTrace(
  runId: string,
  message: string,
  history: { role: string; content: string }[],
): Promise<{ answer: string; edits_applied?: boolean }> {
  try {
    return await post(`/ui/chat/${runId}`, { message, history });
  } catch {
    await ensureBackendRunning();
    return post(`/ui/chat/${runId}`, { message, history });
  }
}
