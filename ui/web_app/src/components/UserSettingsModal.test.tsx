import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UserSettingsPanel } from "./UserSettingsPanel";
import { deleteUser, updateUser, updateUserLlmSettings, type User } from "../userApi";

vi.mock("../userApi", () => ({
  updateUser: vi.fn(),
  deleteUser: vi.fn(),
  updateUserLlmSettings: vi.fn(),
}));

const baseUser: User = {
  user_id: "user-1",
  full_name: "User One",
  email: "user@example.com",
  llm_settings: {
    primary: {
      provider: "together",
      model_name: "Qwen/Qwen3.5-397B-A17B",
      api_base: null,
    },
    helper: {
      provider: "together",
      model_name: "Qwen/Qwen3.5-9B",
      api_base: null,
    },
  },
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("UserSettingsPanel", () => {
  it("shows hosted vLLM guidance and saves nested model settings", async () => {
    vi.mocked(updateUserLlmSettings).mockResolvedValue(baseUser);
    const onUpdated = vi.fn();

    render(
      <UserSettingsPanel
        user={baseUser}
        onUpdated={onUpdated}
        onDeleted={vi.fn()}
      />,
    );

    const providerSelects = screen.getAllByRole("combobox");
    fireEvent.change(providerSelects[0], { target: { value: "hosted_vllm" } });

    expect(screen.getByText(/Use the plain model name here\./i)).toBeInTheDocument();

    const textboxes = screen.getAllByRole("textbox");
    fireEvent.change(textboxes[0], { target: { value: "Meta-Llama-3.1-70B-Instruct" } });
    fireEvent.change(textboxes[1], { target: { value: "http://192.168.1.50:8000/v1" } });

    expect(screen.getByText("hosted_vllm/Meta-Llama-3.1-70B-Instruct")).toBeInTheDocument();
    expect(screen.getByText(/API base:/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save model settings" }));

    await waitFor(() => {
      expect(updateUserLlmSettings).toHaveBeenCalledWith({
        primary: {
          provider: "hosted_vllm",
          model_name: "Meta-Llama-3.1-70B-Instruct",
          api_base: "http://192.168.1.50:8000/v1",
        },
        helper: {
          provider: "together",
          model_name: "Qwen/Qwen3.5-9B",
          api_base: null,
        },
      });
    });
    expect(onUpdated).toHaveBeenCalledTimes(1);
    expect(updateUser).not.toHaveBeenCalled();
    expect(deleteUser).not.toHaveBeenCalled();
  });

  it("blocks hosted vLLM saves without an API base", async () => {
    render(
      <UserSettingsPanel
        user={baseUser}
        onUpdated={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );

    const providerSelects = screen.getAllByRole("combobox");
    fireEvent.change(providerSelects[0], { target: { value: "hosted_vllm" } });
    fireEvent.click(screen.getByRole("button", { name: "Save model settings" }));

    expect(await screen.findByText("Primary API base is required for hosted vLLM.")).toBeInTheDocument();
    expect(updateUserLlmSettings).not.toHaveBeenCalled();
  });
});
