import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TraceChat } from "./TraceChat";
import {
  chatWithTrace,
  clearTraceChatHistory,
  fetchTraceChatHistory,
  restartRun,
} from "../api";

vi.mock("../api", () => ({
  chatWithTrace: vi.fn(),
  clearTraceChatHistory: vi.fn(),
  fetchTraceChatHistory: vi.fn(),
  restartRun: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("TraceChat", () => {
  it("links ampersand-separated step references", async () => {
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([]);
    vi.mocked(chatWithTrace).mockResolvedValue({
      answer: "Review Steps 2 & 3 before continuing.",
      edits_applied: false,
    });
    vi.mocked(clearTraceChatHistory).mockResolvedValue([]);
    vi.mocked(restartRun).mockResolvedValue();
    const onStepLabelClick = vi.fn();

    render(<TraceChat runId="run-1" onStepLabelClick={onStepLabelClick} />);

    await waitFor(() => {
      expect(fetchTraceChatHistory).toHaveBeenCalledWith("run-1");
    });

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
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([]);
    vi.mocked(chatWithTrace).mockResolvedValue({
      answer: "Compare steps 2, 8, and 14 before deciding.",
      edits_applied: false,
    });
    vi.mocked(clearTraceChatHistory).mockResolvedValue([]);
    vi.mocked(restartRun).mockResolvedValue();
    const onStepLabelClick = vi.fn();

    render(<TraceChat runId="run-1" onStepLabelClick={onStepLabelClick} />);

    await waitFor(() => {
      expect(fetchTraceChatHistory).toHaveBeenCalledWith("run-1");
    });

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
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([]);
    vi.mocked(chatWithTrace).mockRejectedValue(new Error("Trace chat timed out after 120 seconds"));
    vi.mocked(clearTraceChatHistory).mockResolvedValue([]);
    vi.mocked(restartRun).mockResolvedValue();

    render(<TraceChat runId="run-1" />);

    await waitFor(() => {
      expect(fetchTraceChatHistory).toHaveBeenCalledWith("run-1");
    });

    const input = screen.getByPlaceholderText("Ask about this trace…");
    fireEvent.change(input, { target: { value: "anything weird?" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    expect(await screen.findByText("Error: Trace chat timed out after 120 seconds")).toBeInTheDocument();
  });

  it("hydrates persisted chat history without rerun buttons", async () => {
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([
      { role: "user", content: "What happened?" },
      { role: "assistant", content: "The agent retried twice." },
    ]);
    vi.mocked(clearTraceChatHistory).mockResolvedValue([]);
    vi.mocked(restartRun).mockResolvedValue();

    render(<TraceChat runId="run-1" />);

    expect(await screen.findByText("What happened?")).toBeInTheDocument();
    expect(await screen.findByText("The agent retried twice.")).toBeInTheDocument();
    expect(screen.queryByText("Re-run with changes")).not.toBeInTheDocument();
  });

  it("clears persisted chat history without confirmation", async () => {
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([
      { role: "user", content: "Keep me around" },
      { role: "assistant", content: "I was persisted." },
    ]);
    vi.mocked(clearTraceChatHistory).mockResolvedValue([]);
    vi.mocked(restartRun).mockResolvedValue();

    render(<TraceChat runId="run-1" />);

    expect(await screen.findByText("Keep me around")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear Chat" }));

    await waitFor(() => {
      expect(clearTraceChatHistory).toHaveBeenCalledWith("run-1");
    });
    expect(screen.queryByText("Keep me around")).not.toBeInTheDocument();
    expect(screen.queryByText("I was persisted.")).not.toBeInTheDocument();
  });

  it("polls pending persisted chat history after reopening a run", async () => {
    vi.mocked(fetchTraceChatHistory)
      .mockResolvedValueOnce([{ role: "user", content: "Will this finish?" }])
      .mockResolvedValueOnce([
        { role: "user", content: "Will this finish?" },
        { role: "assistant", content: "Yes, it finished in the background." },
      ]);
    vi.mocked(clearTraceChatHistory).mockResolvedValue([]);
    vi.mocked(restartRun).mockResolvedValue();

    render(<TraceChat runId="run-1" />);

    expect(await screen.findByText("Will this finish?")).toBeInTheDocument();
    expect(
      await screen.findByText("Yes, it finished in the background.", {}, { timeout: 3000 }),
    ).toBeInTheDocument();
  }, 10000);
});
