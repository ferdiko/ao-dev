import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useProjectRunsData } from "./useProjectRunsData";
import type { Filters } from "../projectFilters";

const {
  fetchProjectMock,
  fetchProjectRunsMock,
  fetchProjectTagsMock,
  subscribeMock,
} = vi.hoisted(() => ({
  fetchProjectMock: vi.fn(),
  fetchProjectRunsMock: vi.fn(),
  fetchProjectTagsMock: vi.fn(),
  subscribeMock: vi.fn(),
}));

vi.mock("../projectsApi", () => ({
  fetchProject: fetchProjectMock,
  fetchProjectTags: fetchProjectTagsMock,
}));

vi.mock("../runsApi", () => ({
  fetchProjectRuns: fetchProjectRunsMock,
}));

vi.mock("../serverEvents", () => ({
  subscribe: subscribeMock,
}));

function makeFilters(): Filters {
  return {
    name: { value: "", isRegex: false },
    runId: "",
    version: new Set(),
    tags: new Set(),
    label: new Set(),
    customMetrics: {
      success: { kind: "bool", values: new Set(["true"]) },
    },
    latency: { min: 4, max: 6, enabled: true },
    startTime: { from: "", to: "" },
  };
}

describe("useProjectRunsData", () => {
  beforeEach(() => {
    fetchProjectMock.mockReset();
    fetchProjectRunsMock.mockReset();
    fetchProjectTagsMock.mockReset();
    subscribeMock.mockReset();

    fetchProjectMock.mockResolvedValue({ project_id: "project-1", name: "Project 1", description: "" });
    fetchProjectRunsMock.mockResolvedValue({
      running: [],
      finished: [],
      finished_total: 0,
      distinct_versions: [],
      custom_metric_columns: [],
    });
    fetchProjectTagsMock.mockResolvedValue([]);
    subscribeMock.mockReturnValue(() => {});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("requests runtime and boolean metric filters for completed runs", async () => {
    renderHook(() => useProjectRunsData({
      completedPage: 1,
      completedRowsPerPage: 50,
      completedSort: null,
      filters: makeFilters(),
      projectId: "project-1",
    }));

    await waitFor(() => {
      expect(fetchProjectRunsMock).toHaveBeenCalled();
    });

    const lastCall = fetchProjectRunsMock.mock.calls.at(-1);

    expect(lastCall).toEqual([
      "project-1",
      expect.objectContaining({
        limit: 50,
        offset: 0,
        latency_min: 4,
        latency_max: 6,
        metric_filters: {
          success: { kind: "bool", values: [true] },
        },
      }),
      expect.any(AbortSignal),
    ]);
  });
});
