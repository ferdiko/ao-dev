import { useState } from "react";
import { X } from "lucide-react";
import { updateUser, deleteUser, type User } from "../api";
import { EditableField } from "./EditableField";

export function UserSettingsModal({
  user,
  onClose,
  onUpdated,
  onDeleted,
}: {
  user: User;
  onClose: () => void;
  onUpdated: () => void;
  onDeleted: () => void;
}) {
  // Delete confirmation state
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteInput, setDeleteInput] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleFieldSave = async (field: "full_name" | "email", value: string) => {
    const fullName = field === "full_name" ? value : user.full_name;
    const email = field === "email" ? value : user.email;
    await updateUser(fullName, email);
    onUpdated();
  };

  const handleDelete = async () => {
    setDeleteError(null);
    if (deleteInput !== user.full_name) {
      setDeleteError("Name does not match.");
      return;
    }
    setDeleting(true);
    try {
      await deleteUser(deleteInput);
      onDeleted();
    } catch (err: unknown) {
      if (err instanceof Error) setDeleteError(err.message);
      else setDeleteError("Failed to delete user.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">User Settings</h2>
          <button className="modal-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <h3 className="modal-subtitle">Profile</h3>
        <EditableField
          label="Full Name"
          value={user.full_name}
          onSave={(v) => handleFieldSave("full_name", v)}
        />
        <EditableField
          label="Email"
          value={user.email}
          onSave={(v) => handleFieldSave("email", v)}
          type="email"
        />

        {/* Danger zone */}
        <div className="modal-danger-zone">
          <h3 className="modal-danger-title">Danger Zone</h3>
          <div className="modal-danger-box">
            <div className="modal-danger-row">
              <div className="modal-danger-row-text">
                <strong>Delete user</strong>
                <span>Once deleted, all associated data will be permanently removed.</span>
              </div>
              <button
                className="btn btn-danger-outline"
                onClick={() => setShowDeleteConfirm(true)}
              >
                Delete user
              </button>
            </div>
            {showDeleteConfirm && (
              <div className="modal-danger-confirm">
                <p className="modal-danger-warning">
                  This will permanently delete your user profile and all
                  associated data (experiments, runs, cached LLM calls). This
                  action cannot be undone.
                </p>
                <p className="modal-danger-prompt">
                  Type <strong>{user.full_name}</strong> to confirm:
                </p>
                <input
                  className="modal-input"
                  value={deleteInput}
                  onChange={(e) => setDeleteInput(e.target.value)}
                  placeholder={user.full_name}
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
                    disabled={deleting || deleteInput !== user.full_name}
                  >
                    {deleting ? "Deleting…" : "Delete user"}
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
