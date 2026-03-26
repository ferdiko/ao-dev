import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { chatWithTrace, fetchProjectExperiments, updateRunTags } from "./api";

describe("api", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("serializes repeated tag_id query params for experiment filters", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        type: "experiment_list",
        running: [],
        finished: [],
        finished_total: 0,
        distinct_versions: [],
        custom_metric_columns: [],
      }),
    });

    await fetchProjectExperiments("project-1", { tag_id: ["tag-a", "tag-b"] });

    const [url] = fetchMock.mock.calls[0] as [string];
    const parsed = new URL(url, "http://localhost");

    expect(parsed.searchParams.getAll("tag_id")).toEqual(["tag-a", "tag-b"]);
  });

  it("posts full replacement tag IDs for a run", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ tags: [] }),
    });

    await updateRunTags("session-1", ["tag-a", "tag-b"]);

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];

    expect(url).toBe("/ui/update-run-tags");
    expect(options.method).toBe("POST");
    expect(options.body).toBe(JSON.stringify({ session_id: "session-1", tag_ids: ["tag-a", "tag-b"] }));
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
        json: async () => ({ answer: "ready" }),
      });

    const result = await chatWithTrace("session-1", "hello", []);

    expect(result).toEqual({ answer: "ready" });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/ui/chat/session-1",
      "/_sovara/health",
      "/_sovara/start-server",
      "/ui/chat/session-1",
    ]);
  });
});
