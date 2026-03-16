import { useState, useCallback } from "react";
import { BrowserRouter, Routes, Route, useParams } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { OrgPage } from "./pages/OrgPage";
import { ProjectPage } from "./pages/ProjectPage";
import { RunView } from "./pages/RunView";
import { PriorsPage } from "./pages/PriorsPage";
import { SovaraPage } from "./pages/SovaraPage";
import { useResize } from "./hooks/useResize";
import "./App.css";

const SIDEBAR_MIN = 140;
const SIDEBAR_MAX = 500;
const SIDEBAR_DEFAULT = Math.round(window.innerWidth * 0.16);

function AppLayout({ projectId, children }: { projectId?: string; children: React.ReactNode }) {
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT);

  const onSidebarResize = useCallback((delta: number) => {
    setSidebarWidth((w) => Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, w + delta)));
  }, []);

  const onSidebarHandleDown = useResize("horizontal", onSidebarResize);

  return (
    <div className="app-layout">
      <Sidebar projectId={projectId} style={{ width: sidebarWidth }}>
        <div className="sidebar-resize-handle" onMouseDown={onSidebarHandleDown} />
      </Sidebar>
      <main className="main-content" style={{ marginLeft: sidebarWidth }}>
        {children}
      </main>
    </div>
  );
}

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
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<OrgRoute />} />
        <Route path="/project/:projectId" element={<ProjectRoute />} />
        <Route path="/project/:projectId/run/:sessionId" element={<RunRoute />} />
        <Route path="/project/:projectId/sovara" element={<SovaraRoute />} />
        <Route path="/project/:projectId/priors" element={<PriorsRoute />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
