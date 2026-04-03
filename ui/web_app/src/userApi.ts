import { get, post } from "./api";

export interface User {
  user_id: string;
  full_name: string;
  email: string;
  llm_settings: UserLlmSettings;
}

export type LlmProvider = "anthropic" | "together" | "hosted_vllm";

export interface UserLlmTierSettings {
  provider: LlmProvider;
  model_name: string;
  api_base: string | null;
}

export interface UserLlmSettings {
  primary: UserLlmTierSettings;
  helper: UserLlmTierSettings;
}

export async function fetchUser(): Promise<User | null> {
  const data = await get<{ user: User | null }>("/ui/user");
  return data.user;
}

export async function setupUser(
  fullName: string,
  email: string,
): Promise<User> {
  const data = await post<{ user: User }>("/ui/setup-user", {
    full_name: fullName,
    email,
  });
  return data.user;
}

export async function updateUser(
  fullName: string,
  email: string,
): Promise<User> {
  const data = await post<{ user: User }>("/ui/update-user", {
    full_name: fullName,
    email,
  });
  return data.user;
}

export async function updateUserLlmSettings(
  llmSettings: UserLlmSettings,
): Promise<User> {
  const data = await post<{ user: User }>("/ui/update-user-llm-settings", llmSettings);
  return data.user;
}

export async function deleteUser(confirmationName: string): Promise<void> {
  await post("/ui/delete-user", { confirmation_name: confirmationName });
}
