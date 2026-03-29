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
});
