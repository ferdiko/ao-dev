import { describe, expect, it } from "vitest";

import type { Run } from "./api";
import type { ProjectRun } from "./projectRuns";
import {
  runToProjectRun,
  formatCodeVersionTimestamp,
  parseProjectRunTimestamp,
  sortProjectRuns,
} from "./projectRuns";
import type { Tag } from "./tags";

describe("projectRuns", () => {
  it("maps runs into project rows with UI defaults", () => {
    const tags: Tag[] = [
      { tag_id: "tag-1", name: "baseline", color: "#6F7C8B" },
    ];
    const run: Run = {
      active_runtime_seconds: null,
      color_preview: [],
      custom_metrics: { confidence: 0.95, success: true },
      name: "Run 12",
      runtime_seconds: 12.4,
      run_id: "run-12",
      status: "finished",
      tags,
      timestamp: "2026-03-23 10:11:12",
      thumb_label: true,
      version_date: null,
    };

    expect(runToProjectRun(run)).toEqual({
      codeVersion: "",
      customMetrics: { confidence: 0.95, success: true },
      activeRuntimeSeconds: null,
      id: "run-12",
      latency: "12.4s",
      latencySeconds: 12.4,
      name: "Run 12",
      runId: "run-12",
      status: "finished",
      tags,
      timestamp: "2026-03-23 10:11:12",
      thumbLabel: true,
    });
  });

  it("parses timestamps without a timezone suffix as UTC", () => {
    const expected = Date.UTC(2026, 2, 23, 10, 11, 12);

    expect(parseProjectRunTimestamp("2026-03-23 10:11:12")).toBe(expected);
    expect(parseProjectRunTimestamp("2026-03-23T10:11:12Z")).toBe(expected);
  });

  it("formats code version timestamps using the same UTC parsing flow", () => {
    expect(formatCodeVersionTimestamp("2026-03-23 10:11:12")).not.toBe("2026-03-23 10:11:12");
    expect(formatCodeVersionTimestamp("")).toBe("—");
  });

  it("uses the active runtime checkpoint for running rows", () => {
    const run: Run = {
      active_runtime_seconds: 3.2,
      color_preview: [],
      custom_metrics: {},
      name: "Run 13",
      runtime_seconds: 12.4,
      run_id: "run-13",
      status: "running",
      tags: [],
      timestamp: "2026-03-23 10:11:12",
      thumb_label: null,
      version_date: null,
    };

    expect(runToProjectRun(run)).toMatchObject({
      activeRuntimeSeconds: 3.2,
      latency: "3.2s",
      latencySeconds: 3.2,
    });
  });

  it("sorts numbered run names numerically", () => {
    const baseRun: Omit<ProjectRun, "name" | "runId" | "id"> = {
      activeRuntimeSeconds: null,
      codeVersion: "—",
      customMetrics: {},
      latency: "—",
      latencySeconds: null,
      status: "finished",
      tags: [],
      timestamp: "2026-03-23 10:11:12",
      thumbLabel: null,
    };

    const runs: ProjectRun[] = [
      { ...baseRun, id: "s-10", name: "Run 10", runId: "s-10" },
      { ...baseRun, id: "s-2", name: "Run 2", runId: "s-2" },
      { ...baseRun, id: "s-3", name: "Run 3", runId: "s-3" },
    ];

    const sorted = sortProjectRuns(runs, { direction: "asc", key: "name" });

    expect(sorted.map((run) => run.name)).toEqual(["Run 2", "Run 3", "Run 10"]);
  });
});
