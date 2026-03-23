import { describe, expect, it } from "vitest";

import type { Experiment } from "./api";
import type { ProjectRun } from "./projectRuns";
import { experimentToProjectRun, parseProjectRunTimestamp, sortProjectRuns } from "./projectRuns";

describe("projectRuns", () => {
  it("maps experiments into project rows with UI defaults", () => {
    const experiment: Experiment = {
      color_preview: [],
      result: "Satisfactory",
      run_name: "Run 12",
      session_id: "session-12",
      status: "finished",
      timestamp: "2026-03-23 10:11:12",
      version_date: null,
    };

    expect(experimentToProjectRun(experiment)).toEqual({
      codeVersion: "—",
      comment: "—",
      confidence: null,
      cost: "—",
      id: "session-12",
      input: "—",
      latency: "—",
      name: "Run 12",
      output: "—",
      sessionId: "session-12",
      status: "finished",
      success: true,
      tags: [],
      timestamp: "2026-03-23 10:11:12",
    });
  });

  it("parses timestamps without a timezone suffix as UTC", () => {
    const expected = Date.UTC(2026, 2, 23, 10, 11, 12);

    expect(parseProjectRunTimestamp("2026-03-23 10:11:12")).toBe(expected);
    expect(parseProjectRunTimestamp("2026-03-23T10:11:12Z")).toBe(expected);
  });

  it("sorts numbered run names numerically", () => {
    const baseRun: Omit<ProjectRun, "name" | "sessionId" | "id"> = {
      codeVersion: "—",
      comment: "—",
      confidence: null,
      cost: "—",
      input: "—",
      latency: "—",
      output: "—",
      status: "finished",
      success: null,
      tags: [],
      timestamp: "2026-03-23 10:11:12",
    };

    const runs: ProjectRun[] = [
      { ...baseRun, id: "s-10", name: "Run 10", sessionId: "s-10" },
      { ...baseRun, id: "s-2", name: "Run 2", sessionId: "s-2" },
      { ...baseRun, id: "s-3", name: "Run 3", sessionId: "s-3" },
    ];

    const sorted = sortProjectRuns(runs, { direction: "asc", key: "name" });

    expect(sorted.map((run) => run.name)).toEqual(["Run 2", "Run 3", "Run 10"]);
  });
});
