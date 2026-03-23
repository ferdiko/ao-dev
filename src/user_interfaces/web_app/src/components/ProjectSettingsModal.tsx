import { useState } from "react";
import { X } from "lucide-react";
import { updateProject, deleteProject } from "../api";
import { EditableField } from "./EditableField";

export function ProjectSettingsModal({
  projectId,
  projectName,
  projectDescription,
  onClose,
  onDeleted,
}: {
  projectId: string;
  projectName: string;
  projectDescription: string;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [name, setName] = useState(projectName);
  const [description, setDescription] = useState(projectDescription);

  // Delete confirmation state
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteInput, setDeleteInput] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleFieldSave = async (field: "name" | "description", value: string) => {
    const newName = field === "name" ? value : name;
    const newDescription = field === "description" ? value : description;
    await updateProject(projectId, newName, newDescription);
    if (field === "name") setName(value);
    else setDescription(value);
  };

  const handleDelete = async () => {
    setDeleteError(null);
    if (deleteInput !== name) {
      setDeleteError("Name does not match.");
      return;
    }
    setDeleting(true);
    try {
      await deleteProject(projectId, deleteInput);
      onDeleted();
    } catch (err: unknown) {
      if (err instanceof Error) setDeleteError(err.message);
      else setDeleteError("Failed to delete project.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">Project Settings</h2>
          <button className="modal-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <h3 className="modal-subtitle">General</h3>
        <EditableField
          label="Project Name"
          value={name}
          onSave={(v) => handleFieldSave("name", v)}
        />
        <EditableField
          label="Description"
          value={description}
          onSave={(v) => handleFieldSave("description", v)}
          required={false}
        />

        {/* Danger zone */}
        <div className="modal-danger-zone">
          <h3 className="modal-danger-title">Danger Zone</h3>
          <div className="modal-danger-box">
            <div className="modal-danger-row">
              <div className="modal-danger-row-text">
                <strong>Delete project</strong>
                <span>Once deleted, all associated data will be permanently removed.</span>
              </div>
              <button
                className="btn btn-danger-outline"
                onClick={() => setShowDeleteConfirm(true)}
              >
                Delete project
              </button>
            </div>
            {showDeleteConfirm && (
              <div className="modal-danger-confirm">
                <p className="modal-danger-warning">
                  This will permanently delete this project and all
                  associated data (experiments, runs, cached LLM calls). This
                  action cannot be undone.
                </p>
                <p className="modal-danger-prompt">
                  Type <strong>{name}</strong> to confirm:
                </p>
                <input
                  className="modal-input"
                  value={deleteInput}
                  onChange={(e) => setDeleteInput(e.target.value)}
                  placeholder={name}
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
                    onClick={handleDelete}
                    disabled={deleting || deleteInput !== name}
                  >
                    {deleting ? "Deleting..." : "Delete project"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
