import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TraceChat } from "./TraceChat";
import { chatWithTrace, restartRun } from "../api";

vi.mock("../api", () => ({
  chatWithTrace: vi.fn(),
  restartRun: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("TraceChat", () => {
  it("links ampersand-separated step references", async () => {
    vi.mocked(chatWithTrace).mockResolvedValue({
      answer: "Review Steps 2 & 3 before continuing.",
      edits_applied: false,
    });
    vi.mocked(restartRun).mockResolvedValue();
    const onStepLabelClick = vi.fn();

    render(<TraceChat runId="run-1" onStepLabelClick={onStepLabelClick} />);

    const input = screen.getByPlaceholderText("Ask about this trace…");
    fireEvent.change(input, { target: { value: "Which steps matter?" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    await waitFor(() => {
      expect(chatWithTrace).toHaveBeenCalledWith("run-1", "Which steps matter?", []);
    });

    const stepReference = await screen.findByText("Steps 2 & 3");
    fireEvent.click(stepReference);

    expect(onStepLabelClick).toHaveBeenCalledWith("2");
  });

  it("links comma-separated step references with a final conjunction", async () => {
    vi.mocked(chatWithTrace).mockResolvedValue({
      answer: "Compare steps 2, 8, and 14 before deciding.",
      edits_applied: false,
    });
    vi.mocked(restartRun).mockResolvedValue();
    const onStepLabelClick = vi.fn();

    render(<TraceChat runId="run-1" onStepLabelClick={onStepLabelClick} />);

    const input = screen.getByPlaceholderText("Ask about this trace…");
    fireEvent.change(input, { target: { value: "Which steps should I compare?" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    await waitFor(() => {
      expect(chatWithTrace).toHaveBeenCalledWith("run-1", "Which steps should I compare?", []);
    });

    const stepReference = await screen.findByText("steps 2, 8, and 14");
    fireEvent.click(stepReference);

    expect(onStepLabelClick).toHaveBeenCalledWith("2");
  });

  it("shows backend error detail when chat fails", async () => {
    vi.mocked(chatWithTrace).mockRejectedValue(new Error("Trace chat timed out after 120 seconds"));
    vi.mocked(restartRun).mockResolvedValue();

    render(<TraceChat runId="run-1" />);

    const input = screen.getByPlaceholderText("Ask about this trace…");
    fireEvent.change(input, { target: { value: "anything weird?" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    expect(await screen.findByText("Error: Trace chat timed out after 120 seconds")).toBeInTheDocument();
  });
});
