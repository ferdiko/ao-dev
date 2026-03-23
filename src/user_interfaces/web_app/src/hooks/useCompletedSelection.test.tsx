import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useCompletedSelection } from "./useCompletedSelection";

describe("useCompletedSelection", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("persists selection across remounts within the same filter scope", () => {
    const { result, rerender, unmount } = renderHook(
      ({ filterKey, visibleIds }: { filterKey: string; visibleIds: string[] }) =>
        useCompletedSelection({ filterKey, projectId: "project-1", visibleIds }),
      {
        initialProps: { filterKey: "all", visibleIds: ["run-1", "run-2"] },
      },
    );

    act(() => {
      result.current.toggleSelect("run-1");
    });

    rerender({ filterKey: "all", visibleIds: ["run-3"] });

    expect(result.current.selectedCount).toBe(1);
    expect(result.current.hiddenSelectedCount).toBe(1);
    expect(result.current.selectedIds.has("run-1")).toBe(true);

    unmount();

    const { result: remounted } = renderHook(() =>
      useCompletedSelection({ filterKey: "all", projectId: "project-1", visibleIds: ["run-3"] }),
    );

    expect(remounted.current.selectedCount).toBe(1);
    expect(remounted.current.hiddenSelectedCount).toBe(1);
    expect(remounted.current.selectedIds.has("run-1")).toBe(true);
  });

  it("clears selection when the filter scope changes and does not revive stale selections", async () => {
    const { result, rerender } = renderHook(
      ({ filterKey }: { filterKey: string }) =>
        useCompletedSelection({ filterKey, projectId: "project-1", visibleIds: ["run-1"] }),
      {
        initialProps: { filterKey: "all" },
      },
    );

    act(() => {
      result.current.toggleSelect("run-1");
    });

    expect(result.current.selectedCount).toBe(1);

    rerender({ filterKey: "failed-only" });
    await waitFor(() => {
      expect(result.current.selectedCount).toBe(0);
    });

    rerender({ filterKey: "all" });
    await waitFor(() => {
      expect(result.current.selectedCount).toBe(0);
      expect(result.current.selectedIds.has("run-1")).toBe(false);
    });
  });
});
