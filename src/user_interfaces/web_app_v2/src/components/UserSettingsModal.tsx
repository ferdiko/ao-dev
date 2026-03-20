import { useState } from "react";
import { Pencil, Check, X } from "lucide-react";
import { updateUser, deleteUser, type User } from "../api";

function EditableField({
  label,
  value,
  onSave,
  type = "text",
}: {
  label: string;
  value: string;
  onSave: (value: string) => Promise<void>;
  type?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!draft.trim()) {
      setError(`${label} is required.`);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(draft.trim());
      setEditing(false);
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
      else setError("Failed to save.");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setDraft(value);
    setEditing(false);
    setError(null);
  };

  return (
    <div className="profile-field">
      <div className="profile-field-label">{label}</div>
      {editing ? (
        <div className="profile-field-edit">
          <input
            className="modal-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            type={type}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
              if (e.key === "Escape") handleCancel();
            }}
          />
          {error && <div className="modal-error">{error}</div>}
          <div className="profile-field-edit-actions">
            <button
              className="profile-field-action-btn save"
              onClick={handleSave}
              disabled={saving}
              title="Save"
            >
              <Check size={14} />
            </button>
            <button
              className="profile-field-action-btn cancel"
              onClick={handleCancel}
              title="Cancel"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      ) : (
        <div className="profile-field-display">
          <span className="profile-field-value">{value}</span>
          <button
            className="profile-field-edit-btn"
            onClick={() => {
              setDraft(value);
              setEditing(true);
            }}
            title={`Edit ${label.toLowerCase()}`}
          >
            <Pencil size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

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
