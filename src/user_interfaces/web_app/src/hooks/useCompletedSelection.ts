import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef } from "react";

const COMPLETED_SELECTION_STORAGE_KEY_PREFIX = "web_app:completed_selection";

function getCompletedSelectionStorageKey(projectId: string): string {
  return `${COMPLETED_SELECTION_STORAGE_KEY_PREFIX}:${projectId}`;
}

function loadCompletedSelection(projectId: string, filterKey: string): Set<string> {
  try {
    const raw = sessionStorage.getItem(getCompletedSelectionStorageKey(projectId));
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as { filterKey?: string; ids?: unknown };
    if (parsed.filterKey !== filterKey || !Array.isArray(parsed.ids)) return new Set();
    return new Set(parsed.ids.filter((id): id is string => typeof id === "string"));
  } catch {
    return new Set();
  }
}

function persistCompletedSelection(projectId: string, filterKey: string, selection: Set<string>): void {
  try {
    sessionStorage.setItem(
      getCompletedSelectionStorageKey(projectId),
      JSON.stringify({ filterKey, ids: Array.from(selection) }),
    );
  } catch {
    // Ignore storage failures; selection still works for the current page session.
  }
}

type SelectionState = {
  ids: Set<string>;
  scopeKey: string;
};

type SelectionAction =
  | { type: "clear"; scopeKey: string }
  | { type: "sync"; ids: Set<string>; scopeKey: string }
  | { type: "toggle"; id: string; scopeKey: string; storedSelection: Set<string> }
  | { type: "toggleVisible"; scopeKey: string; storedSelection: Set<string>; visibleIds: string[] };

function completedSelectionReducer(state: SelectionState, action: SelectionAction): SelectionState {
  switch (action.type) {
    case "clear":
      return { ids: new Set(), scopeKey: action.scopeKey };
    case "sync":
      return { ids: action.ids, scopeKey: action.scopeKey };
    case "toggle": {
      const baseSelection = state.scopeKey === action.scopeKey ? state.ids : action.storedSelection;
      const next = new Set(baseSelection);
      if (next.has(action.id)) next.delete(action.id);
      else next.add(action.id);
      return { ids: next, scopeKey: action.scopeKey };
    }
    case "toggleVisible": {
      const baseSelection = state.scopeKey === action.scopeKey ? state.ids : action.storedSelection;
      const next = new Set(baseSelection);
      const shouldClearVisible = action.visibleIds.length > 0 && action.visibleIds.every((id) => next.has(id));
      if (shouldClearVisible) {
        for (const id of action.visibleIds) next.delete(id);
      } else {
        for (const id of action.visibleIds) next.add(id);
      }
      return { ids: next, scopeKey: action.scopeKey };
    }
  }
}

export function useCompletedSelection({
  projectId,
  filterKey,
  visibleIds,
}: {
  projectId?: string;
  filterKey: string;
  visibleIds: string[];
}) {
  const scopeKey = projectId ? `${projectId}:${filterKey}` : "";
  const storedSelection = useMemo(() => {
    if (!projectId) return new Set<string>();
    return loadCompletedSelection(projectId, filterKey);
  }, [projectId, filterKey]);
  const previousScopeRef = useRef({ filterKey, projectId });
  const [selectionState, dispatchSelection] = useReducer(completedSelectionReducer, {
    ids: storedSelection,
    scopeKey,
  });
  const selectedIds = useMemo(
    () => (selectionState.scopeKey === scopeKey ? selectionState.ids : storedSelection),
    [scopeKey, selectionState.ids, selectionState.scopeKey, storedSelection],
  );

  useLayoutEffect(() => {
    const previousProjectId = previousScopeRef.current.projectId;
    const previousFilterKey = previousScopeRef.current.filterKey;
    const projectChanged = previousProjectId !== projectId;
    const filterChanged = !projectChanged && previousFilterKey !== filterKey;

    if (filterChanged) {
      const clearedSelection = new Set<string>();
      dispatchSelection({ type: "sync", ids: clearedSelection, scopeKey });
      if (projectId) {
        persistCompletedSelection(projectId, filterKey, clearedSelection);
      }
    } else if (selectionState.scopeKey !== scopeKey) {
      dispatchSelection({ type: "sync", ids: storedSelection, scopeKey });
    }

    previousScopeRef.current = { filterKey, projectId };
  }, [filterKey, projectId, scopeKey, selectionState.scopeKey, storedSelection]);

  useEffect(() => {
    if (!projectId) return;
    persistCompletedSelection(projectId, filterKey, selectedIds);
  }, [projectId, filterKey, selectedIds]);

  const selectedVisibleCount = useMemo(
    () => visibleIds.reduce((count, id) => count + (selectedIds.has(id) ? 1 : 0), 0),
    [visibleIds, selectedIds],
  );
  const allVisibleSelected = visibleIds.length > 0 && selectedVisibleCount === visibleIds.length;
  const hiddenSelectedCount = Math.max(0, selectedIds.size - selectedVisibleCount);

  const toggleSelect = useCallback((id: string) => {
    dispatchSelection({ type: "toggle", id, scopeKey, storedSelection });
  }, [scopeKey, storedSelection]);

  const toggleSelectAllVisible = useCallback(() => {
    dispatchSelection({ type: "toggleVisible", scopeKey, storedSelection, visibleIds });
  }, [scopeKey, storedSelection, visibleIds]);

  const clearSelection = useCallback(() => {
    dispatchSelection({ type: "clear", scopeKey });
  }, [scopeKey]);

  return {
    allVisibleSelected,
    clearSelection,
    hiddenSelectedCount,
    selectedCount: selectedIds.size,
    selectedIds,
    selectedVisibleCount,
    toggleSelect,
    toggleSelectAllVisible,
  };
}
