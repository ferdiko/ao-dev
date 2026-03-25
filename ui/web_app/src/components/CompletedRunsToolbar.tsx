import type { CSSProperties, RefObject } from "react";
import {
  Check,
  CheckCheck,
  ChevronDown as ChevronDownIcon,
  Eye,
  ExternalLink as ExternalLinkIcon,
  EyeOff,
  Filter as FilterIcon,
  Trash2,
  X,
} from "lucide-react";

export function RunActionsMenu({
  className = "actions-dropdown-menu",
  style,
  onDeleteSelected,
  onOpenSelectedRuns,
}: {
  className?: string;
  style?: CSSProperties;
  onDeleteSelected: () => void;
  onOpenSelectedRuns: () => void;
}) {
  return (
    <div className={className} style={style}>
      <button className="actions-dropdown-item" onClick={onOpenSelectedRuns}>
        <ExternalLinkIcon size={13} />
        Open runs
      </button>
      <button className="actions-dropdown-item actions-dropdown-item-danger" onClick={onDeleteSelected}>
        <Trash2 size={13} />
        Delete
      </button>
    </div>
  );
}

export function CompletedRunsToolbar({
  actionsOpen,
  actionsRef,
  allColumnsVisible,
  columnOptions,
  columnsOpen,
  columnsRef,
  completedTotal,
  filtersActive,
  filtersOpen,
  hiddenSelectedCount,
  onClearSelection,
  onDeleteSelected,
  onOpenSelectedRuns,
  onSelectAllColumns,
  onToggleActions,
  onToggleColumn,
  onToggleColumns,
  onToggleFilters,
  selectedColumnKeys,
  selectedCount,
}: {
  actionsOpen: boolean;
  actionsRef: RefObject<HTMLDivElement | null>;
  allColumnsVisible: boolean;
  columnOptions: Array<{ key: string; label: string }>;
  columnsOpen: boolean;
  columnsRef: RefObject<HTMLDivElement | null>;
  completedTotal: number;
  filtersActive: boolean;
  filtersOpen: boolean;
  hiddenSelectedCount: number;
  onClearSelection: () => void;
  onDeleteSelected: () => void;
  onOpenSelectedRuns: () => void;
  onSelectAllColumns: () => void;
  onToggleActions: () => void;
  onToggleColumn: (key: string) => void;
  onToggleColumns: () => void;
  onToggleFilters: () => void;
  selectedColumnKeys: Set<string>;
  selectedCount: number;
}) {
  return (
    <div className="landing-section-title">
      <span>Completed Runs ({completedTotal})</span>
      {selectedCount > 0 && (
        <div
          className="runs-selection-pill"
          title={hiddenSelectedCount > 0 ? `${selectedCount} selected across pages` : `${selectedCount} selected`}
        >
          <span className="runs-selection-pill-summary">
            <Check size={11} />
            <span>{selectedCount}</span>
          </span>
          <button
            className="runs-selection-pill-clear"
            onClick={onClearSelection}
            title="Clear selection"
          >
            <X size={11} />
          </button>
        </div>
      )}
      <div className="actions-dropdown-wrap" ref={columnsRef}>
        <button className="actions-dropdown-btn" onClick={onToggleColumns}>
          Columns
          <Eye size={12} />
          <ChevronDownIcon size={12} className={`actions-chevron${columnsOpen ? " rotated" : ""}`} />
        </button>
        {columnsOpen && (
          <div className="actions-dropdown-menu columns-dropdown-menu">
            <button className="actions-dropdown-item" onClick={onSelectAllColumns}>
              <CheckCheck size={13} />
              {allColumnsVisible ? "All columns shown" : "Select all"}
            </button>
            {columnOptions.map((column) => (
              <button
                key={column.key}
                className="actions-dropdown-item"
                onClick={() => onToggleColumn(column.key)}
              >
                <span className="columns-dropdown-check">
                  {selectedColumnKeys.has(column.key) ? <Eye size={13} /> : <EyeOff size={13} />}
                </span>
                {column.label}
              </button>
            ))}
          </div>
        )}
      </div>
      <button
        className={`toolbar-icon-btn${filtersOpen ? " toolbar-icon-btn-open" : ""}${filtersActive ? " toolbar-icon-btn-active" : ""}`}
        onClick={onToggleFilters}
        title="Filters"
        aria-label="Open filters"
      >
        <FilterIcon size={14} />
      </button>
      <div className="actions-dropdown-wrap" ref={actionsRef}>
        <button
          className={`actions-dropdown-btn${selectedCount === 0 ? " actions-inactive" : ""}`}
          onClick={onToggleActions}
        >
          {`Actions (${selectedCount})`}
          <ChevronDownIcon size={12} className={`actions-chevron${actionsOpen ? " rotated" : ""}`} />
        </button>
        {actionsOpen && selectedCount > 0 && (
          <RunActionsMenu
            onDeleteSelected={onDeleteSelected}
            onOpenSelectedRuns={onOpenSelectedRuns}
          />
        )}
      </div>
    </div>
  );
}
