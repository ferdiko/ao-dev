import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Settings,
  HelpCircle,
  Users,
  ChevronDown,
  BarChart3,
  Sparkles,
  Lightbulb,
  Play,
} from "lucide-react";
import { mockProjects } from "../data/mock";
import logoWithSymbol from "../assets/logo_with_symbol.png";

interface NavItem {
  label: string;
  icon: React.ReactNode;
  id: string;
}

const observabilityItems: NavItem[] = [
  { label: "Runs", icon: <Play size={16} />, id: "runs" },
];

const optimizationItems: NavItem[] = [
  {
    label: "Sovara",
    icon: <Sparkles size={16} />,
    id: "sovara",
  },
  { label: "Manage Priors", icon: <Lightbulb size={16} />, id: "db-priors" },
];

const settingsItems: NavItem[] = [
  {
    label: "Project Settings",
    icon: <Settings size={16} />,
    id: "project-settings",
  },
  { label: "Support", icon: <HelpCircle size={16} />, id: "support" },
  {
    label: "Collaboration",
    icon: <Users size={16} />,
    id: "collaboration",
  },
];

export function Sidebar({ projectId, style, children }: { projectId?: string; style?: React.CSSProperties; children?: React.ReactNode }) {
  const navigate = useNavigate();
  const project = projectId ? mockProjects.find((p) => p.id === projectId) : undefined;
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

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
    "db-priors": `/project/${projectId}/priors`,
    "sovara": `/project/${projectId}/sovara`,
  };

  function renderNavItem(item: NavItem) {
    const route = navRoutes[item.id];
    return (
      <button
        key={item.id}
        className="sidebar-item"
        onClick={route ? () => navigate(route) : undefined}
      >
        <span className="sidebar-item-icon">{item.icon}</span>
        {item.label}
      </button>
    );
  }

  return (
    <aside className="sidebar" style={style}>
      {/* Header: Org info */}
      <div className="sidebar-header">
        <div className="sidebar-logo" onClick={() => navigate("/")}>
          <img src={logoWithSymbol} alt="Sovara Labs" />
        </div>

        {/* Project selector dropdown */}
        {project && (
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
                {mockProjects.map((p) => (
                  <button
                    key={p.id}
                    className={`sidebar-project-dropdown-item${p.id === projectId ? " active" : ""}`}
                    onClick={() => {
                      setDropdownOpen(false);
                      navigate(`/project/${p.id}`);
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
            <div className="sidebar-section">Observability</div>
            {observabilityItems.map(renderNavItem)}

            <div className="sidebar-section">Optimization</div>
            {optimizationItems.map(renderNavItem)}
          </>
        ) : (
          <>
            <div className="sidebar-section">Organization</div>
            <button
              className="sidebar-item active"
              onClick={() => navigate("/")}
            >
              <span className="sidebar-item-icon">
                <BarChart3 size={16} />
              </span>
              Projects
            </button>
          </>
        )}
      </nav>

      {/* Bottom section: Settings + User */}
      <div className="sidebar-bottom">
        {project && (
          <div className="sidebar-bottom-nav">
            <div className="sidebar-section">Settings</div>
            {settingsItems.map(renderNavItem)}
          </div>
        )}
        <div className="sidebar-footer">
          <div className="sidebar-user">
            <div className="sidebar-avatar">JB</div>
            <div className="sidebar-user-info">
              <div className="sidebar-user-name">Julian Buechel</div>
              <div className="sidebar-user-email">julian@sovara-labs.com</div>
            </div>
          </div>
        </div>
      </div>
      {children}
    </aside>
  );
}
