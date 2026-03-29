import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { chatWithTrace, deletePriorItems, fetchPrior, fetchProjectRuns, keepBackendAlive, updateRunTags } from "./api";

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

  it("retries trace chat after requesting backend startup", async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce({
        ok: false,
        json: async () => ({ ok: false }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ answer: "ready" }),
      });

    const result = await chatWithTrace("run-1", "hello", []);

    expect(result).toEqual({ answer: "ready" });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/ui/chat/run-1",
      "/_sovara/health",
      "/_sovara/start-server",
      "/_sovara/health",
      "/ui/chat/run-1",
    ]);
  });

  it("retries normal GET calls after backend startup when fetch fails", async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce({
        ok: false,
        json: async () => ({ ok: false }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: "p1", name: "Retry", summary: "", content: "" }),
      });

    const result = await fetchPrior("project-1", "p1");

    expect(result.id).toBe("p1");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/ui/priors/p1?project_id=project-1",
      "/_sovara/health",
      "/_sovara/start-server",
      "/_sovara/health",
      "/ui/priors/p1?project_id=project-1",
    ]);
  });

  it("retries normal GET calls after backend startup when proxy returns 503", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: false,
        status: 503,
        json: async () => ({ error: "backend unavailable" }),
      })
      .mockResolvedValueOnce({
        ok: false,
        json: async () => ({ ok: false }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: "p1", name: "Retry", summary: "", content: "" }),
      });

    const result = await fetchPrior("project-1", "p1");

    expect(result.id).toBe("p1");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/ui/priors/p1?project_id=project-1",
      "/_sovara/health",
      "/_sovara/start-server",
      "/_sovara/health",
      "/ui/priors/p1?project_id=project-1",
    ]);
  });

  it("keeps the backend alive through the health endpoint", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: "ok" }),
    });

    await keepBackendAlive();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/health");
  });

  it("surfaces plain-text proxy errors for batch prior mutations", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 423,
      clone: () => ({
        json: async () => {
          throw new Error("not json");
        },
      }),
      text: async () => "Unable to reach priors backend at http://127.0.0.1:5960",
    });

    await expect(deletePriorItems("project-1", [{ kind: "prior", id: "p1" }])).rejects.toThrow(
      "Unable to reach priors backend at http://127.0.0.1:5960",
    );
  });
});
