import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useUserRefresh } from "./useUserRefresh";

const { subscribeMock } = vi.hoisted(() => ({
  subscribeMock: vi.fn(),
}));

vi.mock("../serverEvents", () => ({
  subscribe: subscribeMock,
}));

describe("useUserRefresh", () => {
  beforeEach(() => {
    subscribeMock.mockReset();
    subscribeMock.mockReturnValue(() => {});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("subscribes to user_changed and refreshes when the event arrives", () => {
    const refreshUser = vi.fn();

    renderHook(() => useUserRefresh(refreshUser));

    expect(subscribeMock).toHaveBeenCalledTimes(1);
    expect(subscribeMock).toHaveBeenCalledWith("user_changed", expect.any(Function));

    const handler = subscribeMock.mock.calls[0]?.[1] as ((message: { type: string }) => void) | undefined;
    expect(handler).toBeTypeOf("function");

    handler?.({ type: "user_changed" });

    expect(refreshUser).toHaveBeenCalledTimes(1);
  });
});
