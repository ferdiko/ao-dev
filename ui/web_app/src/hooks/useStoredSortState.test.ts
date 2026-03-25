import { describe, expect, it } from "vitest";

import { toggleSortState } from "./useStoredSortState";

describe("toggleSortState", () => {
  it("starts a new column in ascending order", () => {
    expect(toggleSortState(null, "timestamp")).toEqual({ key: "timestamp", direction: "asc" });
  });

  it("toggles an active column between ascending and descending only", () => {
    expect(toggleSortState({ key: "timestamp", direction: "asc" }, "timestamp")).toEqual({
      key: "timestamp",
      direction: "desc",
    });
    expect(toggleSortState({ key: "timestamp", direction: "desc" }, "timestamp")).toEqual({
      key: "timestamp",
      direction: "asc",
    });
  });
});
