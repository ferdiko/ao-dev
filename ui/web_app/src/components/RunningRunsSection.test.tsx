import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RunningRunsSection } from "./RunningRunsSection";
import type { ProjectRun } from "../projectRuns";

const baseRun: ProjectRun = {
  activeRuntimeSeconds: 3.6,
  codeVersion: "",
  customMetrics: {},
  id: "run-1",
  latency: "3.6s",
  latencySeconds: 3.6,
  name: "Run 1",
  sessionId: "session-1",
  status: "running",
  tags: [],
  thumbLabel: null,
  timestamp: "2026-03-23 10:11:12",
};

describe("RunningRunsSection", () => {
  it("renders running latency as rounded whole seconds", () => {
    render(
      <RunningRunsSection
        currentPage={1}
        formatCodeVersion={(value) => value || "—"}
        formatTimestamp={(value) => value}
        onOpenRun={vi.fn()}
        onRowKeyDown={vi.fn()}
        onSort={vi.fn()}
        rows={[baseRun]}
        rowsPerPage={10}
        setCurrentPage={vi.fn()}
        setRowsPerPage={vi.fn()}
        sort={null}
        totalCount={1}
        totalPages={1}
      />,
    );

    expect(screen.getByText("4s")).toBeInTheDocument();
    expect(screen.queryByText("3.6s")).not.toBeInTheDocument();
  });
});
