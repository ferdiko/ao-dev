import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  post,
} from "./api";
import { fetchProjectRuns, updateRunTags } from "./runsApi";
import {
  abortTraceChat,
  chatWithTrace,
  clearTraceChatHistory,
  fetchTraceChatHistory,
  saveTraceChatHistory,
} from "./traceChatApi";
import { updateUserLlmSettings } from "./userApi";

describe("api", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("serializes repeated tag_id query params for run filters", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        type: "run_list",
        running: [],
        finished: [],
        finished_total: 0,
        distinct_versions: [],
        custom_metric_columns: [],
      }),
    });

    await fetchProjectRuns("project-1", { tag_id: ["tag-a", "tag-b"] });

    const [url] = fetchMock.mock.calls[0] as [string];
    const parsed = new URL(url, "http://localhost");

    expect(parsed.searchParams.getAll("tag_id")).toEqual(["tag-a", "tag-b"]);
  });

  it("serializes latency bounds query params for run filters", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        type: "run_list",
        running: [],
        finished: [],
        finished_total: 0,
        distinct_versions: [],
        custom_metric_columns: [],
      }),
    });

    await fetchProjectRuns("project-1", { latency_min: 1.5, latency_max: 4.2 });

    const [url] = fetchMock.mock.calls[0] as [string];
    const parsed = new URL(url, "http://localhost");

    expect(parsed.searchParams.get("latency_min")).toBe("1.5");
    expect(parsed.searchParams.get("latency_max")).toBe("4.2");
  });

  it("posts full replacement tag IDs for a run", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ tags: [] }),
    });

    await updateRunTags("run-1", ["tag-a", "tag-b"]);

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];

    expect(url).toBe("/ui/update-run-tags");
    expect(options.method).toBe("POST");
    expect(options.body).toBe(JSON.stringify({ run_id: "run-1", tag_ids: ["tag-a", "tag-b"] }));
  });

  it("posts nested user LLM settings", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        user: {
          user_id: "user-1",
          full_name: "User One",
          email: "user@example.com",
          llm_settings: {
            primary: {
              provider: "hosted_vllm",
              model_name: "Meta-Llama-3.1-70B-Instruct",
              api_base: "http://192.168.1.50:8000/v1",
            },
            helper: {
              provider: "anthropic",
              model_name: "claude-haiku-4-5",
              api_base: null,
            },
          },
        },
      }),
    });

    await updateUserLlmSettings({
      primary: {
        provider: "hosted_vllm",
        model_name: "Meta-Llama-3.1-70B-Instruct",
        api_base: "http://192.168.1.50:8000/v1",
      },
      helper: {
        provider: "anthropic",
        model_name: "claude-haiku-4-5",
        api_base: null,
      },
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];

    expect(url).toBe("/ui/update-user-llm-settings");
    expect(options.method).toBe("POST");
    expect(options.body).toBe(JSON.stringify({
      primary: {
        provider: "hosted_vllm",
        model_name: "Meta-Llama-3.1-70B-Instruct",
        api_base: "http://192.168.1.50:8000/v1",
      },
      helper: {
        provider: "anthropic",
        model_name: "claude-haiku-4-5",
        api_base: null,
      },
    }));
  });

  it("retries failed posts after starting the backend", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ error: "proxy failed" }),
      })
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValueOnce({
        ok: true,
        status: 202,
        json: async () => ({ ok: true }),
      })
      .mockResolvedValueOnce({ ok: true, status: 200 })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ tags: [] }),
      });

    await updateRunTags("run-1", ["tag-a"]);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/ui/update-run-tags",
      "/_sovara/health",
      "/_sovara/start-server",
      "/_sovara/health",
      "/ui/update-run-tags",
    ]);
  });

  it("shares one backend startup attempt across concurrent requests", async () => {
    let backendStarted = false;
    let updateAttempts = 0;
    let startAttempts = 0;

    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/ui/update-run-tags") {
        updateAttempts += 1;
        if (!backendStarted && updateAttempts <= 2) {
          return {
            ok: false,
            status: 500,
            json: async () => ({ error: "proxy failed" }),
          };
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({ tags: [] }),
        };
      }

      if (url === "/_sovara/health") {
        return {
          ok: backendStarted,
          status: backendStarted ? 200 : 503,
        };
      }

      if (url === "/_sovara/start-server") {
        startAttempts += 1;
        backendStarted = true;
        return {
          ok: true,
          status: 202,
          json: async () => ({ ok: true }),
        };
      }

      throw new Error(`Unexpected fetch call: ${url}`);
    });

    await Promise.all([
      updateRunTags("run-1", ["tag-a"]),
      updateRunTags("run-2", ["tag-b"]),
    ]);

    expect(startAttempts).toBe(1);
  });

  it("retries trace chat after requesting backend startup", async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce({
        ok: false,
        status: 503,
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 202,
        json: async () => ({ ok: true }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          history: [
            { role: "user", content: "hello" },
            { role: "assistant", content: "ready" },
          ],
        }),
      });

    const result = await chatWithTrace("run-1", "hello", []);

    expect(result).toEqual({
      history: [
        { role: "user", content: "hello" },
        { role: "assistant", content: "ready" },
      ],
    });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/ui/chat/run-1",
      "/_sovara/health",
      "/_sovara/start-server",
      "/_sovara/health",
      "/ui/chat/run-1",
    ]);
  });

  it("passes an AbortSignal through trace chat requests", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ history: [] }),
    });
    const controller = new AbortController();

    await chatWithTrace("run-1", "hello", [], controller.signal);

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/ui/chat/run-1");
    expect(options.signal).toBe(controller.signal);
  });

  it("posts a trace chat abort request for a run", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({ status: "cancelling" }),
    });

    await abortTraceChat("run-1");

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/ui/chat/run-1/abort");
    expect(options.method).toBe("POST");
    expect(options.body).toBe("{}");
  });

  it("fetches persisted trace chat history for a run", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        history: [
          { role: "user", content: "hello" },
          { role: "assistant", content: "hi" },
        ],
      }),
    });

    await expect(fetchTraceChatHistory("run-1")).resolves.toEqual([
      { role: "user", content: "hello" },
      { role: "assistant", content: "hi" },
    ]);

    expect(fetchMock).toHaveBeenCalledWith("/ui/trace-chat/run-1", undefined);
  });

  it("saves persisted trace chat history for a run", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        history: [
          { role: "user", content: "hello" },
          { role: "assistant", content: "hi" },
        ],
      }),
    });

    await saveTraceChatHistory("run-1", [
      { role: "user", content: "hello" },
      { role: "assistant", content: "hi" },
    ]);

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];

    expect(url).toBe("/ui/trace-chat/run-1");
    expect(options.method).toBe("POST");
    expect(options.body).toBe(JSON.stringify({
      history: [
        { role: "user", content: "hello" },
        { role: "assistant", content: "hi" },
      ],
    }));
  });

  it("clears persisted trace chat history for a run", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ history: [] }),
    });

    await expect(clearTraceChatHistory("run-1")).resolves.toEqual([]);

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];

    expect(url).toBe("/ui/trace-chat/run-1/clear");
    expect(options.method).toBe("POST");
    expect(options.body).toBe("{}");
  });

  it("uses backend detail text for failed posts", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: "Trace chat timed out after 120 seconds" }),
    });

    await expect(post("/ui/chat/run-1", { message: "hello" })).rejects.toThrow(
      "Trace chat timed out after 120 seconds",
    );
  });
});
