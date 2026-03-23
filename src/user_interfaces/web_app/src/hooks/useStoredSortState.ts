import { useCallback, useEffect, useMemo, useState } from "react";

type SortDirection = "asc" | "desc";
export type SortState = { key: string; direction: SortDirection } | null;

function isSortState(value: unknown): value is SortState {
  if (value === null) return true;
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as { key?: unknown; direction?: unknown };
  return typeof candidate.key === "string" && (candidate.direction === "asc" || candidate.direction === "desc");
}

function loadStoredSortState(storageKey: string, fallbackState: SortState): SortState {
  try {
    const raw = sessionStorage.getItem(storageKey);
    if (!raw) return fallbackState;
    const parsed = JSON.parse(raw) as unknown;
    return isSortState(parsed) ? parsed : fallbackState;
  } catch {
    return fallbackState;
  }
}

function persistStoredSortState(storageKey: string, value: SortState): void {
  try {
    if (value === null) {
      sessionStorage.removeItem(storageKey);
      return;
    }
    sessionStorage.setItem(storageKey, JSON.stringify(value));
  } catch {
    // Ignore storage failures; the in-memory state still works.
  }
}

export function useStoredSortState({
  fallbackState,
  storageKey,
}: {
  fallbackState: SortState;
  storageKey: string;
}) {
  const storedState = useMemo(
    () => loadStoredSortState(storageKey, fallbackState),
    [storageKey, fallbackState],
  );
  const [stateByKey, setStateByKey] = useState(() => ({
    scopeKey: storageKey,
    value: storedState,
  }));
  const value = stateByKey.scopeKey === storageKey ? stateByKey.value : storedState;

  useEffect(() => {
    persistStoredSortState(storageKey, value);
  }, [storageKey, value]);

  const setValue = useCallback((
    nextValue: SortState | ((previous: SortState) => SortState),
  ) => {
    setStateByKey((previous) => {
      const baseValue = previous.scopeKey === storageKey ? previous.value : storedState;
      const resolvedValue = typeof nextValue === "function"
        ? nextValue(baseValue)
        : nextValue;
      return {
        scopeKey: storageKey,
        value: resolvedValue,
      };
    });
  }, [storageKey, storedState]);

  return [value, setValue] as const;
}
