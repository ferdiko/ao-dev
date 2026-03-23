import { useCallback, useEffect, useMemo, useState } from "react";

const COMPLETED_SELECTION_STORAGE_KEY_PREFIX = "web_app_v2:completed_selection";

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
  const [selectionState, setSelectionState] = useState(() => ({
    ids: storedSelection,
    scopeKey,
  }));
  const selectedIds = selectionState.scopeKey === scopeKey ? selectionState.ids : storedSelection;

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
    setSelectionState((prev) => {
      const baseSelection = prev.scopeKey === scopeKey ? prev.ids : storedSelection;
      const next = new Set(baseSelection);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { ids: next, scopeKey };
    });
  }, [scopeKey, storedSelection]);

  const toggleSelectAllVisible = useCallback(() => {
    setSelectionState((prev) => {
      const baseSelection = prev.scopeKey === scopeKey ? prev.ids : storedSelection;
      const next = new Set(baseSelection);
      const shouldClearVisible = visibleIds.length > 0 && visibleIds.every((id) => next.has(id));
      if (shouldClearVisible) {
        for (const id of visibleIds) next.delete(id);
      } else {
        for (const id of visibleIds) next.add(id);
      }
      return { ids: next, scopeKey };
    });
  }, [scopeKey, storedSelection, visibleIds]);

  const clearSelection = useCallback(() => {
    setSelectionState({ ids: new Set(), scopeKey });
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
