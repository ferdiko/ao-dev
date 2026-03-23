import { useState, useCallback, useEffect, createContext, useContext } from "react";
import { BrowserRouter, Routes, Route, useParams, useNavigate } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { OrgPage } from "./pages/OrgPage";
import { ProjectPage } from "./pages/ProjectPage";
import { RunView } from "./pages/RunView";
import { PriorsPage } from "./pages/PriorsPage";
import { SovaraPage } from "./pages/SovaraPage";
import { SetupProfileModal } from "./components/SetupProfileModal";
import { UserSettingsModal } from "./components/UserSettingsModal";
import { ProjectSettingsModal } from "./components/ProjectSettingsModal";
import { useResize } from "./hooks/useResize";
import { fetchUser, fetchProject, type User } from "./api";
import arrowImg from "./assets/arrow_spiral_tr_bl.png";
import "./App.css";

// ============================================================
// User context — shared between Sidebar and pages
// ============================================================

interface UserContextValue {
  user: User | null | undefined; // undefined = loading, null = not configured
  refreshUser: () => void;
}

const UserContext = createContext<UserContextValue>({ user: undefined, refreshUser: () => {} });

export function useUser() {
  return useContext(UserContext);
}

// ============================================================
// Layout
// ============================================================

const SIDEBAR_MIN = 140;
const SIDEBAR_MAX = 500;
const SIDEBAR_DEFAULT = 240;

function AppLayout({ projectId, children }: { projectId?: string; children: React.ReactNode }) {
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT);
  const { user, refreshUser } = useUser();
  const navigate = useNavigate();
  const [showSetupProfile, setShowSetupProfile] = useState(false);
  const [showUserSettings, setShowUserSettings] = useState(false);
  const [showProjectSettings, setShowProjectSettings] = useState(false);
  const [project, setProject] = useState<{ project_id: string; name: string; description: string } | null>(null);

  useEffect(() => {
    if (projectId) {
      fetchProject(projectId).then(setProject);
    }
  }, [projectId]);

  const onSidebarResize = useCallback((delta: number) => {
    setSidebarWidth((w) => Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, w + delta)));
  }, []);

  const onSidebarHandleDown = useResize("horizontal", onSidebarResize);

  return (
    <div className="app-layout">
      <Sidebar
        projectId={projectId}
        style={{ width: sidebarWidth }}
        user={user}
        onSetupProfile={() => setShowSetupProfile(true)}
        onUserSettings={() => setShowUserSettings(true)}
        onProjectSettings={() => setShowProjectSettings(true)}
      >
        <div className="sidebar-resize-handle" onMouseDown={onSidebarHandleDown} />
      </Sidebar>
      <main className="main-content" style={{ marginLeft: sidebarWidth }}>
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
      {showUserSettings && user && (
        <UserSettingsModal
          user={user}
          onClose={() => setShowUserSettings(false)}
          onUpdated={() => {
            setShowUserSettings(false);
            refreshUser();
          }}
          onDeleted={() => {
            setShowUserSettings(false);
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
    <AppLayout projectId={projectId}>
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

function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);

  const refreshUser = useCallback(() => {
    fetchUser().then(setUser);
  }, []);

  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  return (
    <UserContext.Provider value={{ user, refreshUser }}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<OrgRoute />} />
          <Route path="/project/:projectId" element={<ProjectRoute />} />
          <Route path="/project/:projectId/run/:sessionId" element={<RunRoute />} />
          <Route path="/project/:projectId/sovara" element={<SovaraRoute />} />
          <Route path="/project/:projectId/priors" element={<PriorsRoute />} />
        </Routes>
      </BrowserRouter>
    </UserContext.Provider>
  );
}

export default App;
