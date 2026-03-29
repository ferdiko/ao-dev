import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "./Sidebar";
import { fetchProjects } from "../api";

vi.mock("../api", () => ({
  fetchProjects: vi.fn(),
}));

vi.mock("../serverEvents", () => ({
  subscribe: vi.fn(() => () => {}),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Sidebar", () => {
  it("hides unsupported optimization entries", async () => {
    vi.mocked(fetchProjects).mockResolvedValue([
      {
        project_id: "project-1",
        name: "Alpha",
        description: "",
        created_at: "2026-03-25T00:00:00Z",
        last_run_at: null,
        num_runs: 0,
        num_users: 0,
        locations: [],
        location_warning: false,
      },
    ]);

    render(
      <MemoryRouter initialEntries={["/project/project-1"]}>
        <Sidebar projectId="project-1" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Runs")).toBeInTheDocument());

    expect(screen.getByText("SovaraDB")).toBeInTheDocument();
    expect(screen.getByText("Optimization")).toBeInTheDocument();
    expect(screen.queryByText("Manage Priors")).not.toBeInTheDocument();
    expect(screen.queryByText("Collaboration")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sovara" })).not.toBeInTheDocument();
  });

  it("opens support through the sidebar callback", async () => {
    vi.mocked(fetchProjects).mockResolvedValue([
      {
        project_id: "project-1",
        name: "Alpha",
        description: "",
        created_at: "2026-03-25T00:00:00Z",
        last_run_at: null,
        num_runs: 0,
        num_users: 0,
        locations: [],
        location_warning: false,
      },
    ]);
    const onSupport = vi.fn();

    render(
      <MemoryRouter initialEntries={["/project/project-1"]}>
        <Sidebar projectId="project-1" onSupport={onSupport} />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Support")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Support" }));

    expect(onSupport).toHaveBeenCalledTimes(1);
  });
});
