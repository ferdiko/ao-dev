import { get, post } from "./api";
import type { Tag } from "./tags";

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

export async function pickDirectory(): Promise<string | null> {
  const data = await post<{ path: string | null }>("/ui/pick-directory", {});
  return data.path;
}

export async function createProject(
  name: string,
  description: string,
  location: string,
): Promise<{ project_id: string; name: string }> {
  return post("/ui/create-project", { name, description, location });
}

export async function updateProjectLocation(
  projectId: string,
  oldLocation: string,
  newLocation: string,
): Promise<void> {
  await post("/ui/update-project-location", {
    project_id: projectId,
    old_location: oldLocation,
    new_location: newLocation,
  });
}

export async function deleteProjectLocation(
  projectId: string,
  location: string,
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
  const data = await post<{ project: { project_id: string; name: string; description: string } }>(
    "/ui/update-project",
    {
      project_id: projectId,
      name,
      description,
    },
  );
  return data.project;
}

export async function deleteProject(
  projectId: string,
  confirmationName: string,
): Promise<void> {
  await post("/ui/delete-project", {
    project_id: projectId,
    confirmation_name: confirmationName,
  });
}

export async function fetchProjects(): Promise<Project[]> {
  const data = await get<{ projects: Project[] }>("/ui/projects");
  return data.projects;
}

export async function fetchProject(
  projectId: string,
): Promise<{ project_id: string; name: string; description: string }> {
  return get(`/ui/projects/${projectId}`);
}

export async function fetchProjectTags(projectId: string): Promise<Tag[]> {
  const data = await get<{ tags: Tag[] }>(`/ui/projects/${projectId}/tags`);
  return data.tags;
}

export async function createProjectTag(projectId: string, name: string, color: string): Promise<Tag> {
  const data = await post<{ tag: Tag }>(`/ui/projects/${projectId}/tags`, { name, color });
  return data.tag;
}

export async function deleteProjectTag(projectId: string, tagId: string): Promise<void> {
  await post(`/ui/projects/${projectId}/tags/delete`, { tag_id: tagId });
}
