import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Breadcrumb } from "../components/Breadcrumb";
import { useUser } from "../userContext";
import {
  fetchProjects,
  pickDirectory,
  createProject,
  type Project,
} from "../api";
import { Play, Users, Calendar, Clock, FolderOpen, AlertTriangle, X, Settings } from "lucide-react";
import arrowLr from "../assets/arrow_lr.png";
import { subscribe } from "../serverEvents";
import { ProjectLocationsModal } from "../components/ProjectLocationsModal";
import { ProjectSettingsModal } from "../components/ProjectSettingsModal";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  // Backend sends naive UTC timestamps — append Z so Date parses as UTC
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: d.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
  });
}

function NewProjectModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const [creating, setCreating] = useState(false);

  const handleBrowse = async () => {
    setPicking(true);
    setError(null);
    try {
      const path = await pickDirectory();
      if (path) setLocation(path);
    } catch {
      setError("Failed to open folder picker.");
    } finally {
      setPicking(false);
    }
  };

  const handleCreate = async () => {
    setError(null);
    if (!name.trim()) {
      setError("Project name is required.");
      return;
    }
    if (!location.trim()) {
      setError("Project location is required.");
      return;
    }
    setCreating(true);
    try {
      await createProject(name.trim(), description.trim(), location.trim());
      onCreated();
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
      else setError("Failed to create project.");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">New Project</h2>
          <button className="modal-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <label className="modal-label">
          Name <span className="modal-required">*</span>
        </label>
        <input
          className="modal-input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="my-project"
          autoFocus
        />

        <label className="modal-label">Description</label>
        <input
          className="modal-input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Optional description"
        />

        <label className="modal-label">
          Location <span className="modal-required">*</span>
        </label>
        <div className="modal-location-row">
          <span className="modal-location-display">
            {location || "No folder selected"}
          </span>
          <button
            className="btn btn-secondary"
            onClick={handleBrowse}
            disabled={picking}
          >
            <FolderOpen size={14} />
            {picking ? "Opening…" : "Browse"}
          </button>
        </div>

        {error && <div className="modal-error">{error}</div>}

        <div className="modal-actions">
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={handleCreate}
            disabled={creating}
          >
            {creating ? "Creating…" : "Create Project"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function OrgPage() {
  const navigate = useNavigate();
  const { user } = useUser();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNewProject, setShowNewProject] = useState(false);
  const [locationsProject, setLocationsProject] = useState<Project | null>(null);
  const [settingsProject, setSettingsProject] = useState<Project | null>(null);

  const loadProjects = useCallback(() => {
    fetchProjects()
      .then(setProjects)
      .catch((err) => console.error("Failed to fetch projects:", err))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadProjects();
  }, [loadProjects, user]);

  // Refetch when server signals a project was created (e.g. from CLI)
  useEffect(() => {
    return subscribe("project_list_changed", loadProjects);
  }, [loadProjects]);

  return (
    <div className="project-page">
      <Breadcrumb items={[{ label: "Projects" }]} />
      <div className="org-page">
        <div className="org-header">
          <div>
            <h1 className="org-title">Projects</h1>
            <p className="org-subtitle">
              {projects.length} project{projects.length !== 1 ? "s" : ""}
            </p>
          </div>
          {!loading && projects.length === 0 && user && (
            <div className="org-empty-hint">
              <span className="org-empty-hint-text">Create your first project</span>
              <img src={arrowLr} alt="" className="org-empty-hint-arrow" />
            </div>
          )}
          <button
            className="btn btn-primary"
            onClick={() => setShowNewProject(true)}
            disabled={!user}
          >
            + New Project
          </button>
        </div>

        {loading ? (
          <p style={{ padding: "2rem", color: "#888" }}>Loading projects…</p>
        ) : projects.length === 0 ? (
          <p style={{ padding: "2rem", color: "#888" }}>
            No projects yet.
          </p>
        ) : (
          <div className="project-grid">
            {projects.map((project) => (
              <div
                key={project.project_id}
                className="project-card"
                onClick={() => navigate(`/project/${project.project_id}`)}
              >
                <div className="project-card-name">
                  {project.name}
                  {project.location_warning && (
                    <button
                      className="project-card-warning"
                      onClick={(e) => {
                        e.stopPropagation();
                        setLocationsProject(project);
                      }}
                    >
                      <AlertTriangle size={14} />
                      <span>Project folder not found</span>
                    </button>
                  )}
                  <button
                    className="project-card-settings"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSettingsProject(project);
                    }}
                    title="Project settings"
                  >
                    <Settings size={16} />
                  </button>
                </div>
                <div className="project-card-desc">{project.description}</div>
                <div className="project-card-meta">
                  <div className="project-card-meta-item">
                    <Play size={12} />
                    <span className="project-card-meta-value">
                      {project.num_runs}
                    </span>{" "}
                    runs
                  </div>
                  <div className="project-card-meta-item">
                    <Users size={12} />
                    <span className="project-card-meta-value">
                      {project.num_users}
                    </span>{" "}
                    user{project.num_users !== 1 ? "s" : ""}
                  </div>
                  <div className="project-card-meta-item">
                    <Calendar size={12} />
                    {formatDate(project.created_at)}
                  </div>
                  <div className="project-card-meta-item">
                    <Clock size={12} />
                    {formatDate(project.last_run_at)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showNewProject && (
        <NewProjectModal
          onClose={() => setShowNewProject(false)}
          onCreated={() => {
            setShowNewProject(false);
            loadProjects();
          }}
        />
      )}

      {locationsProject && (
        <ProjectLocationsModal
          project={locationsProject}
          onClose={() => {
            setLocationsProject(null);
            loadProjects();
          }}
        />
      )}

      {settingsProject && (
        <ProjectSettingsModal
          projectId={settingsProject.project_id}
          projectName={settingsProject.name}
          projectDescription={settingsProject.description}
          onClose={() => setSettingsProject(null)}
          onDeleted={() => setSettingsProject(null)}
        />
      )}
    </div>
  );
}
