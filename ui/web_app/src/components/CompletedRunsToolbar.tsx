import type { RefObject } from "react";
import { Check, X, ChevronDown as ChevronDownIcon, Sparkles, Trash2, ExternalLink as ExternalLinkIcon } from "lucide-react";

export function CompletedRunsToolbar({
  actionsOpen,
  actionsRef,
  completedTotal,
  hiddenSelectedCount,
  onAskSovara,
  onClearSelection,
  onDeleteSelected,
  onOpenSelectedRuns,
  onToggleActions,
  selectedCount,
}: {
  actionsOpen: boolean;
  actionsRef: RefObject<HTMLDivElement | null>;
  completedTotal: number;
  hiddenSelectedCount: number;
  onAskSovara: () => void;
  onClearSelection: () => void;
  onDeleteSelected: () => void;
  onOpenSelectedRuns: () => void;
  onToggleActions: () => void;
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
      <div className="actions-dropdown-wrap" ref={actionsRef}>
        <button
          className={`actions-dropdown-btn${selectedCount === 0 ? " actions-inactive" : ""}`}
          onClick={onToggleActions}
        >
          Actions
          <ChevronDownIcon size={12} className={`actions-chevron${actionsOpen ? " rotated" : ""}`} />
        </button>
        {actionsOpen && selectedCount > 0 && (
          <div className="actions-dropdown-menu">
            <button className="actions-dropdown-item" onClick={onOpenSelectedRuns}>
              <ExternalLinkIcon size={13} />
              Open runs
            </button>
            <button className="actions-dropdown-item" onClick={onAskSovara}>
              <Sparkles size={13} />
              Ask Sovara
            </button>
            <button className="actions-dropdown-item actions-dropdown-item-danger" onClick={onDeleteSelected}>
              <Trash2 size={13} />
              Delete
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
