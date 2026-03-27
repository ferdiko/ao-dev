import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CompletedRunsTable } from "./CompletedRunsTable";
import type { ProjectRun } from "../projectRuns";

const baseRun: ProjectRun = {
  id: "run-1",
  sessionId: "session-1",
  name: "Run 1",
  status: "finished",
  timestamp: "2026-03-23 10:11:12",
  latency: "12.4s",
  latencySeconds: 12.4,
  activeRuntimeSeconds: null,
  codeVersion: "",
  thumbLabel: null,
  customMetrics: {},
  tags: [],
};

describe("CompletedRunsTable", () => {
  it("renders tag pills for tagged runs", () => {
    render(
      <CompletedRunsTable
        allVisibleSelected={false}
        formatCodeVersion={(value) => value || "—"}
        formatTimestamp={(value) => value}
        metricColumns={[]}
        onOpenRun={vi.fn()}
        onRowKeyDown={vi.fn()}
        onRowContextMenu={vi.fn()}
        onSort={vi.fn()}
        onToggleSelect={vi.fn()}
        onToggleSelectAll={vi.fn()}
        runs={[{
          ...baseRun,
          tags: [
            { tag_id: "tag-1", name: "baseline", color: "#6F7C8B" },
            { tag_id: "tag-2", name: "ship", color: "#7E8F6A" },
          ],
        }]}
        selectedIds={new Set()}
        sort={null}
        visibleColumnKeys={new Set(["name", "tags"])}
      />,
    );

    expect(screen.getByText("baseline")).toBeInTheDocument();
    expect(screen.getByText("ship")).toBeInTheDocument();
  });

  it("renders an em dash when a run has no tags", () => {
    render(
      <CompletedRunsTable
        allVisibleSelected={false}
        formatCodeVersion={(value) => value || "—"}
        formatTimestamp={(value) => value}
        metricColumns={[]}
        onOpenRun={vi.fn()}
        onRowKeyDown={vi.fn()}
        onRowContextMenu={vi.fn()}
        onSort={vi.fn()}
        onToggleSelect={vi.fn()}
        onToggleSelectAll={vi.fn()}
        runs={[baseRun]}
        selectedIds={new Set()}
        sort={null}
        visibleColumnKeys={new Set(["name", "tags"])}
      />,
    );

    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("does not sort when the tags header is clicked", () => {
    const onSort = vi.fn();

    render(
      <CompletedRunsTable
        allVisibleSelected={false}
        formatCodeVersion={(value) => value || "—"}
        formatTimestamp={(value) => value}
        metricColumns={[]}
        onOpenRun={vi.fn()}
        onRowKeyDown={vi.fn()}
        onRowContextMenu={vi.fn()}
        onSort={onSort}
        onToggleSelect={vi.fn()}
        onToggleSelectAll={vi.fn()}
        runs={[baseRun]}
        selectedIds={new Set()}
        sort={null}
        visibleColumnKeys={new Set(["name", "tags"])}
      />,
    );

    fireEvent.click(screen.getAllByRole("columnheader", { name: "Tags" }).at(-1)!);

    expect(onSort).not.toHaveBeenCalled();
  });
});
