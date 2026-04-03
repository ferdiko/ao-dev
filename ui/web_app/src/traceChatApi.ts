import { get, post } from "./api";

export interface TraceChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface TraceChatResponse {
  history: TraceChatHistoryMessage[];
  answer?: string;
  edits_applied?: boolean;
}

export async function fetchTraceChatHistory(runId: string): Promise<TraceChatHistoryMessage[]> {
  const data = await get<{ history: TraceChatHistoryMessage[] }>(`/ui/trace-chat/${runId}`);
  return data.history;
}

export async function saveTraceChatHistory(
  runId: string,
  history: TraceChatHistoryMessage[],
): Promise<TraceChatHistoryMessage[]> {
  const data = await post<{ history: TraceChatHistoryMessage[] }>(`/ui/trace-chat/${runId}`, { history });
  return data.history;
}

export async function clearTraceChatHistory(runId: string): Promise<TraceChatHistoryMessage[]> {
  const data = await post<{ history: TraceChatHistoryMessage[] }>(`/ui/trace-chat/${runId}/clear`, {});
  return data.history;
}

export function prefetchTrace(runId: string): void {
  post(`/ui/prefetch/${runId}`, {}).catch(() => {});
}

export async function abortTraceChat(runId: string): Promise<void> {
  await post(`/ui/chat/${runId}/abort`, {});
}

export async function chatWithTrace(
  runId: string,
  message: string,
  history: { role: string; content: string }[],
  signal?: AbortSignal,
): Promise<TraceChatResponse> {
  return post(`/ui/chat/${runId}`, { message, history }, { signal });
}
