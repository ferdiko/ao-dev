import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Settings,
  HelpCircle,
  ChevronDown,
  BarChart3,
  Play,
  UserPlus,
  PanelLeft,
} from "lucide-react";
import { fetchProjects, type Project } from "../projectsApi";
import type { User } from "../userApi";
import { subscribe } from "../serverEvents";
import sovaraWordmark from "../assets/sovara_wordmark.png";

interface NavItem {
  label: string;
  icon: React.ReactNode;
  id: string;
}

const observabilityItems: NavItem[] = [
  { label: "Runs", icon: <Play size={16} />, id: "runs" },
];

const settingsItems: NavItem[] = [
  {
    label: "User Settings",
    icon: <Settings size={16} />,
    id: "user-settings",
  },
  {
    label: "Project Settings",
    icon: <Settings size={16} />,
    id: "project-settings",
  },
  { label: "Support", icon: <HelpCircle size={16} />, id: "support" },
];

export function Sidebar({ projectId, style, children, user, collapsed, onToggleCollapse, onSetupProfile, onProjectSettings, onSupport }: {
  projectId?: string;
  style?: React.CSSProperties;
  children?: React.ReactNode;
  user?: User | null;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onSetupProfile?: () => void;
  onProjectSettings?: () => void;
  onSupport?: () => void;
}) {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const project = projectId ? projects.find((p) => p.project_id === projectId) : undefined;

  // Fetch projects for the dropdown
  useEffect(() => {
    fetchProjects()
      .then(setProjects)
      .catch((err) => console.error("Failed to fetch projects:", err));
  }, []);

  // Refetch when projects change (name update, deletion, new project from CLI)
  useEffect(() => {
    return subscribe("project_list_changed", () => {
      fetchProjects().then(setProjects);
    });
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    if (!dropdownOpen) return;
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [dropdownOpen]);

  const navRoutes: Record<string, string> = {
    runs: `/project/${projectId}`,
    "user-settings": "/settings",
  };

  const callbackItems: Record<string, (() => void) | undefined> = {
    "project-settings": onProjectSettings,
    support: onSupport,
  };

  function renderNavItem(item: NavItem) {
    const callback = callbackItems[item.id];
    const route = navRoutes[item.id];
    if (item.id === "project-settings" && !project) {
      return null;
    }
    return (
      <button
        key={item.id}
        className={`sidebar-item${collapsed ? " sidebar-item-collapsed" : ""}`}
        onClick={callback ?? (route ? () => navigate(route) : undefined)}
        title={collapsed ? item.label : undefined}
      >
        <span className="sidebar-item-icon">{item.icon}</span>
        {!collapsed && item.label}
      </button>
    );
  }

  return (
    <aside className={`sidebar${collapsed ? " sidebar-collapsed" : ""}`} style={style}>
      {/* Header */}
      <div className="sidebar-header">
        {collapsed ? (
          <button className="sidebar-collapse-btn" onClick={onToggleCollapse} title="Expand sidebar">
            <PanelLeft size={18} />
          </button>
        ) : (
          <div className="sidebar-header-row">
            <button className="sidebar-logo" onClick={() => navigate("/")} type="button" aria-label="Go to projects">
              <img src={sovaraWordmark} alt="Sovara" />
            </button>
            <button className="sidebar-collapse-btn" onClick={onToggleCollapse} title="Collapse sidebar">
              <PanelLeft size={18} />
            </button>
          </div>
        )}

        {/* Project selector dropdown */}
        {!collapsed && project && (
          <div className="sidebar-project-selector-row" ref={dropdownRef}>
            <button
              className="sidebar-project-selector"
              onClick={() => setDropdownOpen(!dropdownOpen)}
            >
              <span>{project.name}</span>
              <ChevronDown size={14} />
            </button>
            {dropdownOpen && (
              <div className="sidebar-project-dropdown">
                {projects.map((p) => (
                  <button
                    key={p.project_id}
                    className={`sidebar-project-dropdown-item${p.project_id === projectId ? " active" : ""}`}
                    onClick={() => {
                      setDropdownOpen(false);
                      navigate(`/project/${p.project_id}`);
                    }}
                  >
                    {p.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav">
        {project ? (
          <>
            {!collapsed && <div className="sidebar-section">Observability</div>}
            {observabilityItems.map(renderNavItem)}
          </>
        ) : (
          <>
            {!collapsed && <div className="sidebar-section">Organization</div>}
            <button
              className={`sidebar-item active${collapsed ? " sidebar-item-collapsed" : ""}`}
              onClick={() => navigate("/")}
              title={collapsed ? "Projects" : undefined}
            >
              <span className="sidebar-item-icon">
                <BarChart3 size={16} />
              </span>
              {!collapsed && "Projects"}
            </button>
          </>
        )}
      </nav>

      {/* Bottom section: Settings + User */}
      <div className="sidebar-bottom">
        <div className="sidebar-bottom-nav">
          {!collapsed && <div className="sidebar-section">Settings</div>}
          {settingsItems.map(renderNavItem)}
        </div>
        <div className="sidebar-footer">
          {user ? (
            collapsed ? (
              <div className="sidebar-avatar" title={user.full_name}>
                {((parts) => parts.length === 1 ? parts[0][0] : parts[0][0] + parts[parts.length - 1][0])(user.full_name.split(" ")).toUpperCase()}
              </div>
            ) : (
              <div className="sidebar-user">
                <div className="sidebar-avatar">
                  {((parts) => parts.length === 1 ? parts[0][0] : parts[0][0] + parts[parts.length - 1][0])(user.full_name.split(" ")).toUpperCase()}
                </div>
                <div className="sidebar-user-info">
                  <div className="sidebar-user-name">{user.full_name}</div>
                  <div className="sidebar-user-email">{user.email}</div>
                </div>
              </div>
            )
          ) : user === null && onSetupProfile ? (
            <button className="sidebar-setup-profile" onClick={onSetupProfile}>
              <UserPlus size={16} />
              {!collapsed && "Setup Profile"}
            </button>
          ) : null}
        </div>
      </div>
      {children}
    </aside>
  );
}
