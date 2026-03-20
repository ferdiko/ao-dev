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

// ============================================================
// Experiment endpoints (project-scoped)
// ============================================================

interface ExperimentListResponse {
  type: string;
  experiments: Experiment[];
  has_more: boolean;
}

export async function fetchProjectExperiments(
  projectId: string
): Promise<ExperimentListResponse> {
  return get<ExperimentListResponse>(
    `/ui/projects/${projectId}/experiments`
  );
}

export async function fetchMoreProjectExperiments(
  projectId: string,
  offset: number
): Promise<ExperimentListResponse> {
  return get<ExperimentListResponse>(
    `/ui/projects/${projectId}/experiments/more?offset=${offset}`
  );
}

// ============================================================
// Graph endpoints
// ============================================================

export async function fetchGraph(sessionId: string) {
  return get<{ type: string; session_id: string; payload: { nodes: unknown[]; edges: unknown[] } }>(
    `/ui/graph/${sessionId}`
  );
}
