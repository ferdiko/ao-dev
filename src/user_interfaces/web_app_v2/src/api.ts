/**
 * API layer for communicating with the ao backend.
 *
 * All backend communication goes through this module.
 * Types use the same field names as the backend JSON responses.
 */

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

export interface Experiment {
  session_id: string;
  status: "running" | "finished";
  timestamp: string;
  color_preview: string[];
  version_date: string | null;
  run_name: string;
  result: string;
}

// ============================================================
// HTTP helpers
// ============================================================

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(path);
  if (!resp.ok) {
    throw new Error(`GET ${path} failed: ${resp.status}`);
  }
  return resp.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const data = await resp.json().catch(() => null);
    throw new Error(data?.error ?? `POST ${path} failed: ${resp.status}`);
  }
  return resp.json();
}

export { post };

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

export async function deleteProject(
  projectId: string,
  confirmationName: string
): Promise<void> {
  await post("/ui/delete-project", {
    project_id: projectId,
    confirmation_name: confirmationName,
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
// Experiment endpoints (project-scoped)
// ============================================================

export interface ExperimentQueryParams {
  limit?: number;
  offset?: number;
  sort?: string;
  dir?: string;
  name?: string;
  session_id?: string;
  success?: string[];
  version?: string[];
  time_from?: string;
  time_to?: string;
}

interface ProjectExperimentsResponse {
  type: string;
  running: Experiment[];
  finished: Experiment[];
  finished_total: number;
  distinct_versions: string[];
}

export async function fetchProjectExperiments(
  projectId: string,
  params?: ExperimentQueryParams,
  signal?: AbortSignal,
): Promise<ProjectExperimentsResponse> {
  const qs = new URLSearchParams();
  if (params) {
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    if (params.offset !== undefined) qs.set("offset", String(params.offset));
    if (params.sort) qs.set("sort", params.sort);
    if (params.dir) qs.set("dir", params.dir);
    if (params.name) qs.set("name", params.name);
    if (params.session_id) qs.set("session_id", params.session_id);
    if (params.time_from) qs.set("time_from", params.time_from);
    if (params.time_to) qs.set("time_to", params.time_to);
    if (params.success) for (const v of params.success) qs.append("success", v);
    if (params.version) for (const v of params.version) qs.append("version", v);
  }
  const query = qs.toString();
  const url = `/ui/projects/${projectId}/experiments${query ? `?${query}` : ""}`;
  const resp = await fetch(url, { signal });
  if (!resp.ok) throw new Error(`GET ${url} failed: ${resp.status}`);
  return resp.json();
}

// ============================================================
// Graph endpoints
// ============================================================

export async function fetchGraph(sessionId: string) {
  return get<{ type: string; session_id: string; payload: { nodes: unknown[]; edges: unknown[] } }>(
    `/ui/graph/${sessionId}`
  );
}
