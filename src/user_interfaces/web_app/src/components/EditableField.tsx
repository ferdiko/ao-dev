import { useState } from "react";
import { Pencil, Check, X } from "lucide-react";

export function EditableField({
  label,
  value,
  onSave,
  type = "text",
  required = true,
}: {
  label: string;
  value: string;
  onSave: (value: string) => Promise<void>;
  type?: string;
  required?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (required && !draft.trim()) {
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
