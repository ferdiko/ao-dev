import { useNavigate } from "react-router-dom";
import { Breadcrumb } from "../components/Breadcrumb";
import { UserSettingsPanel } from "../components/UserSettingsPanel";
import { useUser } from "../userContext";

export function UserSettingsPage() {
  const { user, refreshUser } = useUser();
  const navigate = useNavigate();

  if (user === undefined) {
    return (
      <div className="project-page">
        <div className="empty-state">
          <div className="empty-state-title">Loading...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="project-page">
      <Breadcrumb items={[{ label: "User Settings" }]} />

      <div className="project-page-header">
        <div className="project-page-title">User Settings</div>
      </div>

      <div className="settings-page-scroll">
        {user ? (
          <UserSettingsPanel
            user={user}
            onUpdated={refreshUser}
            onDeleted={() => {
              refreshUser();
              navigate("/");
            }}
          />
        ) : (
          <div className="settings-empty-state">
            <div className="empty-state-title">No user configured</div>
            <p className="settings-empty-copy">
              Set up your profile from the sidebar to configure trace chat models.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
