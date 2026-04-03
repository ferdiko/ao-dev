import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TraceChat } from "./TraceChat";
import { restartRun } from "../runsApi";
import {
  abortTraceChat,
  chatWithTrace,
  clearTraceChatHistory,
  fetchTraceChatHistory,
} from "../traceChatApi";

vi.mock("../runsApi", () => ({
  restartRun: vi.fn(),
}));

vi.mock("../traceChatApi", () => ({
  abortTraceChat: vi.fn(),
  chatWithTrace: vi.fn(),
  clearTraceChatHistory: vi.fn(),
  fetchTraceChatHistory: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("TraceChat", () => {
  it("returns control after a response in Strict Mode", async () => {
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([]);
    vi.mocked(chatWithTrace).mockResolvedValue({
      history: [
        { role: "user", content: "What happened?" },
        { role: "assistant", content: "Here is the answer." },
      ],
      edits_applied: false,
    });
    vi.mocked(abortTraceChat).mockResolvedValue();
    vi.mocked(clearTraceChatHistory).mockResolvedValue([]);
    vi.mocked(restartRun).mockResolvedValue();

    render(
      <StrictMode>
        <TraceChat runId="run-1" />
      </StrictMode>,
    );

    await waitFor(() => {
      expect(fetchTraceChatHistory).toHaveBeenCalledWith("run-1");
    });

    const input = screen.getByPlaceholderText("Ask about this trace…");
    fireEvent.change(input, { target: { value: "What happened?" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    expect(await screen.findByText("Here is the answer.")).toBeInTheDocument();
    expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask about this trace…")).toBeEnabled();
  });

  it("links ampersand-separated step references", async () => {
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([]);
    vi.mocked(chatWithTrace).mockResolvedValue({
      history: [
        { role: "user", content: "Which steps matter?" },
        { role: "assistant", content: "Review Steps 2 & 3 before continuing." },
      ],
      edits_applied: false,
    });
    vi.mocked(abortTraceChat).mockResolvedValue();
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
      expect(chatWithTrace).toHaveBeenCalledWith("run-1", "Which steps matter?", [], expect.anything());
    });

    const stepReference = await screen.findByText("Steps 2 & 3");
    fireEvent.click(stepReference);

    expect(onStepLabelClick).toHaveBeenCalledWith("2");
  });

  it("links comma-separated step references with a final conjunction", async () => {
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([]);
    vi.mocked(chatWithTrace).mockResolvedValue({
      history: [
        { role: "user", content: "Which steps should I compare?" },
        { role: "assistant", content: "Compare steps 2, 8, and 14 before deciding." },
      ],
      edits_applied: false,
    });
    vi.mocked(abortTraceChat).mockResolvedValue();
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
      expect(chatWithTrace).toHaveBeenCalledWith("run-1", "Which steps should I compare?", [], expect.anything());
    });

    const stepReference = await screen.findByText("steps 2, 8, and 14");
    fireEvent.click(stepReference);

    expect(onStepLabelClick).toHaveBeenCalledWith("2");
  });

  it("shows backend error detail when chat fails", async () => {
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([]);
    vi.mocked(chatWithTrace).mockRejectedValue(new Error("Trace chat timed out after 120 seconds"));
    vi.mocked(abortTraceChat).mockResolvedValue();
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

  it("hides the thinking bubble when an answer arrives", async () => {
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([]);
    vi.mocked(chatWithTrace).mockResolvedValue({
      history: [
        { role: "user", content: "What happened?" },
        { role: "assistant", content: "Here is the answer." },
      ],
      edits_applied: false,
    });
    vi.mocked(abortTraceChat).mockResolvedValue();
    vi.mocked(clearTraceChatHistory).mockResolvedValue([]);
    vi.mocked(restartRun).mockResolvedValue();

    render(<TraceChat runId="run-1" />);

    await waitFor(() => {
      expect(fetchTraceChatHistory).toHaveBeenCalledWith("run-1");
    });

    const input = screen.getByPlaceholderText("Ask about this trace…");
    fireEvent.change(input, { target: { value: "What happened?" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    expect(screen.getByText("Thinking…")).toBeInTheDocument();
    expect(await screen.findByText("Here is the answer.")).toBeInTheDocument();
    expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask about this trace…")).toBeEnabled();
  });

  it("hydrates persisted chat history without rerun buttons", async () => {
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([
      { role: "user", content: "What happened?" },
      { role: "assistant", content: "The agent retried twice." },
    ]);
    vi.mocked(abortTraceChat).mockResolvedValue();
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
    vi.mocked(abortTraceChat).mockResolvedValue();
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
    vi.mocked(abortTraceChat).mockResolvedValue();
    vi.mocked(clearTraceChatHistory).mockResolvedValue([]);
    vi.mocked(restartRun).mockResolvedValue();

    render(<TraceChat runId="run-1" />);

    expect(await screen.findByText("Will this finish?")).toBeInTheDocument();
    expect(
      await screen.findByText("Yes, it finished in the background.", {}, { timeout: 3000 }),
    ).toBeInTheDocument();
  }, 10000);

  it("hydrates persisted history if the direct chat request never settles", async () => {
    vi.mocked(fetchTraceChatHistory)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        { role: "user", content: "Did it finish?" },
        { role: "assistant", content: "Yes, it finished in the background." },
      ]);
    vi.mocked(chatWithTrace).mockImplementation(
      () => new Promise(() => {}) as Promise<{ history: { role: "user" | "assistant"; content: string }[] }>
    );
    vi.mocked(abortTraceChat).mockResolvedValue();
    vi.mocked(clearTraceChatHistory).mockResolvedValue([]);
    vi.mocked(restartRun).mockResolvedValue();

    render(<TraceChat runId="run-1" />);

    await waitFor(() => {
      expect(fetchTraceChatHistory).toHaveBeenCalledWith("run-1");
    });

    const input = screen.getByPlaceholderText("Ask about this trace…");
    fireEvent.change(input, { target: { value: "Did it finish?" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    expect(screen.getByText("Thinking…")).toBeInTheDocument();
    expect(screen.getByText("Did it finish?")).toBeInTheDocument();

    expect(
      await screen.findByText("Yes, it finished in the background.", {}, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(screen.getByText("Did it finish?")).toBeInTheDocument();
    expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask about this trace…")).toBeEnabled();
  }, 10000);

  it("stops an in-flight chat request without rendering an error", async () => {
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([]);
    vi.mocked(abortTraceChat).mockImplementation(() => new Promise(() => {}));
    vi.mocked(clearTraceChatHistory).mockResolvedValue([]);
    vi.mocked(restartRun).mockResolvedValue();
    vi.mocked(chatWithTrace).mockImplementation((_runId, _message, _history, signal) => (
      new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
        });
      }) as Promise<{ history: { role: "user" | "assistant"; content: string }[]; edits_applied?: boolean }>
    ));

    render(<TraceChat runId="run-1" />);

    await waitFor(() => {
      expect(fetchTraceChatHistory).toHaveBeenCalledWith("run-1");
    });

    const input = screen.getByPlaceholderText("Ask about this trace…");
    fireEvent.change(input, { target: { value: "Please take a while" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    expect(screen.getByText("Please take a while")).toBeInTheDocument();
    expect(screen.getByText("Thinking…")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Stop trace chat"));

    expect(abortTraceChat).toHaveBeenCalledWith("run-1");
    expect(screen.getByPlaceholderText("Ask about this trace…")).toBeEnabled();
    expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();
    await new Promise((resolve) => {
      setTimeout(resolve, 1500);
    });
    expect(fetchTraceChatHistory).toHaveBeenCalledTimes(1);
    expect(screen.queryByTitle("Stop trace chat")).not.toBeInTheDocument();
    expect(screen.getByText("Please take a while")).toBeInTheDocument();
    expect(screen.queryByText(/^Error:/)).not.toBeInTheDocument();
  }, 10000);

  it("returns control after stop in Strict Mode", async () => {
    vi.mocked(fetchTraceChatHistory).mockResolvedValue([]);
    vi.mocked(abortTraceChat).mockResolvedValue();
    vi.mocked(clearTraceChatHistory).mockResolvedValue([]);
    vi.mocked(restartRun).mockResolvedValue();
    vi.mocked(chatWithTrace).mockImplementation((_runId, _message, _history, signal) => (
      new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
        });
      }) as Promise<{ history: { role: "user" | "assistant"; content: string }[]; edits_applied?: boolean }>
    ));

    render(
      <StrictMode>
        <TraceChat runId="run-1" />
      </StrictMode>,
    );

    await waitFor(() => {
      expect(fetchTraceChatHistory).toHaveBeenCalledWith("run-1");
    });

    const input = screen.getByPlaceholderText("Ask about this trace…");
    fireEvent.change(input, { target: { value: "Please take a while" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    expect(screen.getByText("Thinking…")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Stop trace chat"));

    expect(abortTraceChat).toHaveBeenCalledWith("run-1");
    await waitFor(() => {
      expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();
      expect(screen.getByPlaceholderText("Ask about this trace…")).toBeEnabled();
    });
  }, 10000);
});
