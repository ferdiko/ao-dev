import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, X } from "lucide-react";
import logoBlack from "../assets/logo_black.png";

export function RunTabsHeader({
  activeRunId,
  onCloseTab,
  onSwitchTab,
  projectId,
  projectName,
  runIds,
  runIdsKey,
  tabNames,
}: {
  activeRunId: string;
  onCloseTab: (id: string) => void;
  onSwitchTab: (id: string) => void;
  projectId?: string;
  projectName: string;
  runIds: string[];
  runIdsKey: string;
  tabNames: Map<string, string>;
}) {
  const headerRef = useRef<HTMLDivElement>(null);
  const activeTabRef = useRef<HTMLDivElement>(null);
  const [dividerPath, setDividerPath] = useState("");
  const [tabFillPath, setTabFillPath] = useState("");

  useEffect(() => {
    const header = headerRef.current;
    const tab = activeTabRef.current;
    if (!header || !tab) return;

    const measure = () => {
      const hRect = header.getBoundingClientRect();
      const tRect = tab.getBoundingClientRect();
      const w = hRect.width;
      const h = hRect.height;
      const tl = tRect.left - hRect.left;
      const tr = tRect.right - hRect.left;
      const tt = tRect.top - hRect.top;
      const r = 8;

      setDividerPath(
        `M 0,${h} L ${tl - r},${h}` +
        ` A ${r} ${r} 0 0 0 ${tl},${h - r}` +
        ` L ${tl},${tt + r}` +
        ` A ${r} ${r} 0 0 1 ${tl + r},${tt}` +
        ` L ${tr - r},${tt}` +
        ` A ${r} ${r} 0 0 1 ${tr},${tt + r}` +
        ` L ${tr},${h - r}` +
        ` A ${r} ${r} 0 0 0 ${tr + r},${h}` +
        ` L ${w},${h}`,
      );
      setTabFillPath(
        `M ${tl - r},${h}` +
        ` A ${r} ${r} 0 0 0 ${tl},${h - r}` +
        ` L ${tl},${tt + r}` +
        ` A ${r} ${r} 0 0 1 ${tl + r},${tt}` +
        ` L ${tr - r},${tt}` +
        ` A ${r} ${r} 0 0 1 ${tr},${tt + r}` +
        ` L ${tr},${h - r}` +
        ` A ${r} ${r} 0 0 0 ${tr + r},${h}` +
        ` Z`,
      );
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(header);
    observer.observe(tab);
    return () => observer.disconnect();
  }, [activeRunId, runIdsKey, tabNames]);

  return (
    <div className="run-view-panel-header" ref={headerRef}>
      <Link to="/" className="breadcrumb-link">Projects</Link>
      <ChevronRight size={14} className="breadcrumb-separator" />
      <Link to={`/project/${projectId}`} className="breadcrumb-link">{projectName || "Project"}</Link>
      <ChevronRight size={14} className="breadcrumb-separator" />
      <Link to={`/project/${projectId}`} className="breadcrumb-link">Runs</Link>
      <ChevronRight size={14} className="breadcrumb-separator" />
      {dividerPath && (
        <svg className="run-tab-divider-svg" preserveAspectRatio="none">
          <path d={tabFillPath} fill="var(--color-surface)" stroke="none" />
          <path d={dividerPath} fill="none" stroke="var(--color-border)" strokeWidth="1" />
        </svg>
      )}
      <div className="run-tabs" role="tablist" aria-label="Open runs">
        {runIds.map((id) => (
          <div
            key={id}
            ref={id === activeRunId ? activeTabRef : undefined}
            className={`run-tab${id === activeRunId ? " active" : ""}`}
          >
            <button
              className="run-tab-button"
              onClick={() => onSwitchTab(id)}
              type="button"
              role="tab"
              aria-selected={id === activeRunId}
            >
              <img src={logoBlack} alt="" className="run-tab-icon" />
              <span className="run-tab-label">{tabNames.get(id) || id.slice(0, 8)}</span>
            </button>
            <button
              className="run-tab-close"
              onClick={() => onCloseTab(id)}
              type="button"
              aria-label={`Close run ${tabNames.get(id) || id.slice(0, 8)}`}
            >
              <X size={12} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
