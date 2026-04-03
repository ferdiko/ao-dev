import { useState, useCallback, useEffect } from "react";
import { BrowserRouter, Routes, Route, useParams, useNavigate } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { OrgPage } from "./pages/OrgPage";
import { ProjectPage } from "./pages/ProjectPage";
import { RunView } from "./pages/RunView";
import { PriorsPage } from "./pages/PriorsPage";
import { SovaraPage } from "./pages/SovaraPage";
import { UserSettingsPage } from "./pages/UserSettingsPage";
import { SetupProfileModal } from "./components/SetupProfileModal";
import { ProjectSettingsModal } from "./components/ProjectSettingsModal";
import { SupportModal } from "./components/SupportModal";
import { useResize } from "./hooks/useResize";
import { useUserRefresh } from "./hooks/useUserRefresh";
import { fetchProject } from "./projectsApi";
import { fetchUser, type User } from "./userApi";
import { UserContext, useUser } from "./userContext";
import arrowImg from "./assets/arrow_spiral_tr_bl.png";
import "./App.css";

// ============================================================
// Layout
// ============================================================

const SIDEBAR_MIN = 140;
const SIDEBAR_MAX = 500;
const SIDEBAR_DEFAULT = 240;
const SIDEBAR_COLLAPSED = 48;

function AppLayout({ projectId, defaultCollapsed, children }: { projectId?: string; defaultCollapsed?: boolean; children: React.ReactNode }) {
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(defaultCollapsed ?? false);
  const { user, refreshUser } = useUser();
  const navigate = useNavigate();
  const [showSetupProfile, setShowSetupProfile] = useState(false);
  const [showProjectSettings, setShowProjectSettings] = useState(false);
  const [showSupport, setShowSupport] = useState(false);
  const [project, setProject] = useState<{ project_id: string; name: string; description: string } | null>(null);

  useEffect(() => {
    if (projectId) {
      fetchProject(projectId).then(setProject);
    }
  }, [projectId]);

  const effectiveWidth = sidebarCollapsed ? SIDEBAR_COLLAPSED : sidebarWidth;

  const onSidebarResize = useCallback((delta: number) => {
    setSidebarWidth((w) => Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, w + delta)));
  }, []);

  const onSidebarHandleDown = useResize("horizontal", onSidebarResize);

  return (
    <div className="app-layout">
      <Sidebar
        projectId={projectId}
        style={{ width: effectiveWidth }}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
        user={user}
        onSetupProfile={() => setShowSetupProfile(true)}
        onProjectSettings={() => setShowProjectSettings(true)}
        onSupport={() => setShowSupport(true)}
      >
        {!sidebarCollapsed && (
          <div className="sidebar-resize-handle" onMouseDown={onSidebarHandleDown} />
        )}
      </Sidebar>
      <main className="main-content" style={{ marginLeft: effectiveWidth }}>
        {children}
      </main>
      {user === null && (
        <div className="onboarding-hint">
          <span className="onboarding-hint-text" style={{ left: 30, bottom: 200 }}>
            Get started by setting up your profile
          </span>
          <img
            src={arrowImg}
            alt=""
            className="onboarding-hint-arrow"
            style={{ left: 50, bottom: 110, width: 130 }}
          />
        </div>
      )}
      {showSetupProfile && (
        <SetupProfileModal
          onClose={() => setShowSetupProfile(false)}
          onCreated={() => {
            setShowSetupProfile(false);
            refreshUser();
          }}
        />
      )}
      {showProjectSettings && project && projectId && (
        <ProjectSettingsModal
          projectId={projectId}
          projectName={project.name}
          projectDescription={project.description}
          onClose={() => {
            setShowProjectSettings(false);
            fetchProject(projectId).then(setProject);
          }}
          onDeleted={() => {
            setShowProjectSettings(false);
            navigate("/");
          }}
        />
      )}
      {showSupport && (
        <SupportModal onClose={() => setShowSupport(false)} />
      )}
    </div>
  );
}

// ============================================================
// Routes
// ============================================================

function OrgRoute() {
  return (
    <AppLayout>
      <OrgPage />
    </AppLayout>
  );
}

function ProjectRoute() {
  const { projectId } = useParams<{ projectId: string }>();
  return (
    <AppLayout projectId={projectId}>
      <ProjectPage />
    </AppLayout>
  );
}

function RunRoute() {
  const { projectId } = useParams<{ projectId: string }>();
  return (
    <AppLayout projectId={projectId} defaultCollapsed>
      <RunView />
    </AppLayout>
  );
}

function SovaraRoute() {
  const { projectId } = useParams<{ projectId: string }>();
  return (
    <AppLayout projectId={projectId}>
      <SovaraPage />
    </AppLayout>
  );
}

function PriorsRoute() {
  const { projectId } = useParams<{ projectId: string }>();
  return (
    <AppLayout projectId={projectId}>
      <PriorsPage />
    </AppLayout>
  );
}

function UserSettingsRoute() {
  return (
    <AppLayout>
      <UserSettingsPage />
    </AppLayout>
  );
}

function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);

  const refreshUser = useCallback(() => {
    fetchUser().then(setUser);
  }, []);

  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  useUserRefresh(refreshUser);

  return (
    <UserContext.Provider value={{ user, refreshUser }}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<OrgRoute />} />
          <Route path="/project/:projectId" element={<ProjectRoute />} />
          <Route path="/project/:projectId/run/:runId" element={<RunRoute />} />
          <Route path="/project/:projectId/sovara" element={<SovaraRoute />} />
          <Route path="/project/:projectId/priors" element={<PriorsRoute />} />
          <Route path="/settings" element={<UserSettingsRoute />} />
        </Routes>
      </BrowserRouter>
    </UserContext.Provider>
  );
}

export default App;
