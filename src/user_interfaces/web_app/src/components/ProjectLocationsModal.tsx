import { useState } from "react";
import { X, Check, AlertTriangle, Trash2, FolderOpen } from "lucide-react";
import {
  pickDirectory,
  updateProjectLocation,
  deleteProjectLocation,
  deleteProject,
  type Project,
  type ProjectLocation,
} from "../api";

export function ProjectLocationsModal({
  project,
  onClose,
}: {
  project: Project;
  onClose: () => void;
}) {
  const [locations, setLocations] = useState<ProjectLocation[]>(project.locations);
  const [error, setError] = useState<string | null>(null);
  const [editingPath, setEditingPath] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);

  // Delete project confirmation
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteInput, setDeleteInput] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const hasWarnings = locations.some((loc) => !loc.valid);

  const handleEdit = async (oldPath: string) => {
    setError(null);
    setEditingPath(oldPath);
    setPicking(true);
    try {
      const newPath = await pickDirectory();
      if (newPath) {
        await updateProjectLocation(project.project_id, oldPath, newPath);
        setLocations((prev) =>
          prev.map((loc) =>
            loc.path === oldPath ? { path: newPath, valid: true } : loc
          )
        );
      }
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
      else setError("Failed to update location.");
    } finally {
      setPicking(false);
      setEditingPath(null);
    }
  };

  const handleDelete = async (path: string) => {
    // If last location, show delete-project confirmation instead
    if (locations.length <= 1) {
      setShowDeleteConfirm(true);
      return;
    }
    setError(null);
    try {
      await deleteProjectLocation(project.project_id, path);
      setLocations((prev) => prev.filter((loc) => loc.path !== path));
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
      else setError("Failed to delete location.");
    }
  };

  const handleDeleteProject = async () => {
    setDeleteError(null);
    if (deleteInput !== project.name) {
      setDeleteError("Name does not match.");
      return;
    }
    setDeleting(true);
    try {
      await deleteProject(project.project_id, deleteInput);
      onClose();
    } catch (err: unknown) {
      if (err instanceof Error) setDeleteError(err.message);
      else setDeleteError("Failed to delete project.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">Project Locations</h2>
          <button className="modal-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {hasWarnings ? (
          <div className="location-warning-banner">
            <AlertTriangle size={14} />
            <span>
              Some registered locations for <strong>{project.name}</strong> could
              not be found on disk. This usually means the project folder was
              moved or deleted. Update the path to point to the new location, or
              remove it.
            </span>
          </div>
        ) : (
          <div className="location-ok-banner">
            <Check size={14} />
            <span>
              All project folders for <strong>{project.name}</strong> are in sync.
            </span>
          </div>
        )}

        {locations.map((loc) => (
          <div
            key={loc.path}
            className={`location-row ${!loc.valid ? "location-row-warning" : ""}`}
          >
            <div className="location-row-left">
              {loc.valid ? (
                <Check size={14} className="location-valid-icon" />
              ) : (
                <AlertTriangle size={14} className="location-warning-icon" />
              )}
              <div className="location-row-text">
                <span className="location-path">{loc.path}</span>
                {!loc.valid && (
                  <span className="location-row-hint">
                    Directory not found or missing .ao configuration
                  </span>
                )}
              </div>
            </div>
            <div className="location-row-actions">
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleEdit(loc.path)}
                disabled={picking}
              >
                <FolderOpen size={14} />
                {picking && editingPath === loc.path
                  ? "Opening..."
                  : "Set new location"}
              </button>
              <button
                className="profile-field-edit-btn"
                onClick={() => handleDelete(loc.path)}
                title={
                  locations.length <= 1
                    ? "Delete project"
                    : "Remove location"
                }
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}

        {error && <div className="modal-error">{error}</div>}

        {showDeleteConfirm && (
          <div className="modal-danger-zone">
            <div className="modal-danger-box">
              <div className="modal-danger-confirm">
                <p className="modal-danger-warning">
                  This is the last location for this project. Removing it will
                  delete the project and all associated data (experiments, runs,
                  cached LLM calls). This action cannot be undone.
                </p>
                <p className="modal-danger-prompt">
                  Type <strong>{project.name}</strong> to confirm:
                </p>
                <input
                  className="modal-input"
                  value={deleteInput}
                  onChange={(e) => setDeleteInput(e.target.value)}
                  placeholder={project.name}
                  autoFocus
                />
                {deleteError && <div className="modal-error">{deleteError}</div>}
                <div className="modal-actions">
                  <button
                    className="btn btn-secondary"
                    onClick={() => {
                      setShowDeleteConfirm(false);
                      setDeleteInput("");
                      setDeleteError(null);
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    className="btn btn-danger"
                    onClick={handleDeleteProject}
                    disabled={deleting || deleteInput !== project.name}
                  >
                    {deleting ? "Deleting..." : "Delete project"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
