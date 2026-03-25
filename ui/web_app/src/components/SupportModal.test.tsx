import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SupportModal } from "./SupportModal";

afterEach(() => {
  cleanup();
});

describe("SupportModal", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });
  });

  it("shows the support contact options, keeps the mailto link, and copies the email", async () => {
    const onClose = vi.fn();

    render(<SupportModal onClose={onClose} />);

    expect(screen.getByRole("heading", { name: "Support" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /email/i })).toHaveAttribute(
      "href",
      "mailto:support@sovara-labs.com",
    );
    expect(screen.getByRole("link", { name: /discord server/i })).toHaveAttribute(
      "href",
      "https://discord.gg/fjsNSa6TAh",
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy email" }));

    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("support@sovara-labs.com");
      expect(screen.getByRole("button", { name: "Email copied" })).toBeInTheDocument();
    });
  });

  it("closes from the action button", () => {
    const onClose = vi.fn();

    render(<SupportModal onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
