import { useState } from "react";
import {
  deleteUser,
  updateUser,
  updateUserLlmSettings,
  type LlmProvider,
  type User,
  type UserLlmSettings,
  type UserLlmTierSettings,
} from "../api";
import { EditableField } from "./EditableField";

const PROVIDER_LABELS: Record<LlmProvider, string> = {
  anthropic: "Anthropic",
  together: "Together",
  hosted_vllm: "Hosted vLLM",
};

const MODEL_PLACEHOLDERS: Record<LlmProvider, string> = {
  anthropic: "claude-sonnet-4-5",
  together: "Qwen/Qwen3.5-397B-A17B",
  hosted_vllm: "Meta-Llama-3.1-70B-Instruct",
};

const API_BASE_EXAMPLE = "http://192.168.1.50:8000/v1";

function cloneLlmSettings(settings: UserLlmSettings): UserLlmSettings {
  return {
    primary: { ...settings.primary },
    helper: { ...settings.helper },
  };
}

function normalizeTierSettings(settings: UserLlmTierSettings): UserLlmTierSettings {
  const modelName = settings.model_name.trim();
  const apiBase = settings.api_base?.trim() || null;
  return {
    provider: settings.provider,
    model_name: modelName,
    api_base: settings.provider === "hosted_vllm" ? apiBase : null,
  };
}

function normalizeLlmSettings(settings: UserLlmSettings): UserLlmSettings {
  return {
    primary: normalizeTierSettings(settings.primary),
    helper: normalizeTierSettings(settings.helper),
  };
}

function resolvedLiteLlmTarget(settings: UserLlmTierSettings): string {
  const modelName = settings.model_name.trim();
  switch (settings.provider) {
    case "anthropic":
      return `anthropic/${modelName || MODEL_PLACEHOLDERS.anthropic}`;
    case "together":
      return `together_ai/${modelName || MODEL_PLACEHOLDERS.together}`;
    case "hosted_vllm":
      return `hosted_vllm/${modelName || MODEL_PLACEHOLDERS.hosted_vllm}`;
  }
}

function validateLlmSettings(settings: UserLlmSettings): string | null {
  for (const [tier, tierSettings] of Object.entries(settings) as Array<[keyof UserLlmSettings, UserLlmTierSettings]>) {
    if (!tierSettings.model_name.trim()) {
      return `${tier === "primary" ? "Primary" : "Helper"} model name is required.`;
    }
    if (tierSettings.provider === "hosted_vllm" && !(tierSettings.api_base?.trim())) {
      return `${tier === "primary" ? "Primary" : "Helper"} API base is required for hosted vLLM.`;
    }
  }
  return null;
}

function LlmSettingsCard({
  title,
  description,
  settings,
  onChange,
}: {
  title: string;
  description: string;
  settings: UserLlmTierSettings;
  onChange: (patch: Partial<UserLlmTierSettings>) => void;
}) {
  const isHostedVllm = settings.provider === "hosted_vllm";

  return (
    <div className="llm-settings-card">
      <div className="llm-settings-card-header">
        <h4 className="llm-settings-card-title">{title}</h4>
        <p className="llm-settings-card-description">{description}</p>
      </div>

      <label className="modal-label">Provider</label>
      <select
        className="modal-input"
        value={settings.provider}
        onChange={(e) => onChange({ provider: e.target.value as LlmProvider })}
      >
        <option value="anthropic">{PROVIDER_LABELS.anthropic}</option>
        <option value="together">{PROVIDER_LABELS.together}</option>
        <option value="hosted_vllm">{PROVIDER_LABELS.hosted_vllm}</option>
      </select>

      <label className="modal-label">Model Name</label>
      <input
        className="modal-input"
        value={settings.model_name}
        onChange={(e) => onChange({ model_name: e.target.value })}
        placeholder={MODEL_PLACEHOLDERS[settings.provider]}
      />

      {isHostedVllm && (
        <>
          <label className="modal-label">API Base</label>
          <input
            className="modal-input"
            value={settings.api_base ?? ""}
            onChange={(e) => onChange({ api_base: e.target.value })}
            placeholder={API_BASE_EXAMPLE}
          />
          <p className="modal-helper-text">
            Enter the full base URL for your hosted vLLM server. IPs are common, but
            Sovara will accept whatever you enter and pass it through at runtime.
          </p>
        </>
      )}

      <div className="llm-settings-preview">
        <div className="llm-settings-preview-label">LiteLLM target</div>
        <code className="llm-settings-preview-code">{resolvedLiteLlmTarget(settings)}</code>
        {isHostedVllm && (
          <div className="llm-settings-preview-meta">
            API base: <code>{settings.api_base?.trim() || API_BASE_EXAMPLE}</code>
          </div>
        )}
      </div>

      {isHostedVllm && (
        <p className="modal-helper-text">
          Use the plain model name here. Sovara adds the <code>hosted_vllm/</code> prefix
          automatically when calling LiteLLM.
        </p>
      )}
    </div>
  );
}

export function UserSettingsPanel({
  user,
  onUpdated,
  onDeleted,
}: {
  user: User;
  onUpdated: () => void;
  onDeleted: () => void;
}) {
  const [llmSettings, setLlmSettings] = useState<UserLlmSettings>(() => cloneLlmSettings(user.llm_settings));
  const [savingLlmSettings, setSavingLlmSettings] = useState(false);
  const [llmError, setLlmError] = useState<string | null>(null);

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteInput, setDeleteInput] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const normalizedDraft = normalizeLlmSettings(llmSettings);
  const normalizedSaved = normalizeLlmSettings(user.llm_settings);
  const llmSettingsChanged = JSON.stringify(normalizedDraft) !== JSON.stringify(normalizedSaved);

  const handleFieldSave = async (field: "full_name" | "email", value: string) => {
    const fullName = field === "full_name" ? value : user.full_name;
    const email = field === "email" ? value : user.email;
    await updateUser(fullName, email);
    onUpdated();
  };

  const updateTierSettings = (tier: keyof UserLlmSettings, patch: Partial<UserLlmTierSettings>) => {
    setLlmSettings((current) => ({
      ...current,
      [tier]: {
        ...current[tier],
        ...patch,
      },
    }));
    setLlmError(null);
  };

  const handleLlmSettingsSave = async () => {
    const error = validateLlmSettings(normalizedDraft);
    if (error) {
      setLlmError(error);
      return;
    }

    setSavingLlmSettings(true);
    setLlmError(null);
    try {
      await updateUserLlmSettings(normalizedDraft);
      onUpdated();
    } catch (err: unknown) {
      if (err instanceof Error) setLlmError(err.message);
      else setLlmError("Failed to save trace chat model settings.");
    } finally {
      setSavingLlmSettings(false);
    }
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
    <div className="settings-panel">
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

      <h3 className="modal-subtitle">Trace Chat Models</h3>
      <p className="modal-helper-text modal-helper-text-top">
        Configure the planner model used for tool-calling and the helper model used for
        summarization and verification.
      </p>

      <div className="llm-settings-grid">
        <LlmSettingsCard
          title="Primary Model"
          description="Used for the planner and edit operations. This model must support tool calling."
          settings={llmSettings.primary}
          onChange={(patch) => updateTierSettings("primary", patch)}
        />
        <LlmSettingsCard
          title="Helper Model"
          description="Used for summarization, verification, and other lower-cost helper work."
          settings={llmSettings.helper}
          onChange={(patch) => updateTierSettings("helper", patch)}
        />
      </div>

      {llmError && <div className="modal-error">{llmError}</div>}

      <div className="modal-actions llm-settings-actions">
        <button
          className="btn btn-primary"
          onClick={handleLlmSettingsSave}
          disabled={savingLlmSettings || !llmSettingsChanged}
        >
          {savingLlmSettings ? "Saving…" : "Save model settings"}
        </button>
      </div>

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
                associated data (runs, runs, cached LLM calls). This
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
  );
}
