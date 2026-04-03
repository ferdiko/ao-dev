import { useEffect, useRef, useState } from "react";
import {
  restartRun,
} from "../runsApi";
import {
  abortTraceChat,
  chatWithTrace,
  clearTraceChatHistory,
  fetchTraceChatHistory,
  type TraceChatHistoryMessage,
} from "../traceChatApi";

const PENDING_HISTORY_POLL_MS = 1000;
const PENDING_HISTORY_POLL_TIMEOUT_MS = 120000;

function findLastAssistantIndex(history: TraceChatHistoryMessage[]): number | null {
  for (let index = history.length - 1; index >= 0; index -= 1) {
    if (history[index]?.role === "assistant") {
      return index;
    }
  }
  return null;
}

function historiesMatch(
  left: TraceChatHistoryMessage[],
  right: TraceChatHistoryMessage[],
): boolean {
  if (left.length !== right.length) {
    return false;
  }

  return left.every((message, index) => (
    message.role === right[index]?.role
    && message.content === right[index]?.content
  ));
}

function historyStartsWith(
  history: TraceChatHistoryMessage[],
  prefix: TraceChatHistoryMessage[],
): boolean {
  if (history.length < prefix.length) {
    return false;
  }

  return prefix.every((message, index) => (
    message.role === history[index]?.role
    && message.content === history[index]?.content
  ));
}

export function useTraceChatSession(runId: string) {
  const [history, setHistory] = useState<TraceChatHistoryMessage[]>([]);
  const [rerunnableAssistantIndex, setRerunnableAssistantIndex] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [isPendingReplySuppressed, setIsPendingReplySuppressed] = useState(false);
  const activeAbortControllerRef = useRef<AbortController | null>(null);
  const lastMessage = history[history.length - 1];
  const hasPendingPersistedReply = lastMessage?.role === "user" && !isPendingReplySuppressed;

  const clearActiveRequest = (abortController?: AbortController) => {
    if (abortController && activeAbortControllerRef.current !== abortController) {
      return;
    }

    activeAbortControllerRef.current = null;
    setIsLoading(false);
  };

  useEffect(() => () => {
    activeAbortControllerRef.current?.abort();
    activeAbortControllerRef.current = null;
  }, []);

  useEffect(() => {
    let cancelled = false;
    activeAbortControllerRef.current?.abort();
    activeAbortControllerRef.current = null;
    setHistory([]);
    setRerunnableAssistantIndex(null);
    setIsLoading(false);
    setIsHistoryLoading(true);
    setIsPendingReplySuppressed(false);

    fetchTraceChatHistory(runId)
      .then((nextHistory) => {
        if (!cancelled) {
          setHistory(nextHistory);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error("Failed to load trace chat history:", error);
          setHistory([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsHistoryLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [runId]);

  useEffect(() => {
    if (isHistoryLoading || isClearing || !hasPendingPersistedReply) {
      return;
    }

    let cancelled = false;
    const deadline = Date.now() + PENDING_HISTORY_POLL_TIMEOUT_MS;
    const expectedHistory = history;

    const poll = async () => {
      while (!cancelled && Date.now() < deadline) {
        await new Promise((resolve) => {
          setTimeout(resolve, PENDING_HISTORY_POLL_MS);
        });
        if (cancelled) {
          return;
        }

        try {
          const nextHistory = await fetchTraceChatHistory(runId);
          if (cancelled) {
            return;
          }
          if (!historyStartsWith(nextHistory, expectedHistory)) {
            continue;
          }
          if (!historiesMatch(history, nextHistory)) {
            setHistory(nextHistory);
            setRerunnableAssistantIndex(null);
            if (isLoading && nextHistory[nextHistory.length - 1]?.role === "assistant") {
              activeAbortControllerRef.current = null;
              setIsLoading(false);
            }
            return;
          }
        } catch (error) {
          if (!cancelled) {
            console.error("Failed to refresh pending trace chat history:", error);
          }
        }
      }
    };

    void poll();
    return () => {
      cancelled = true;
    };
  }, [hasPendingPersistedReply, history, isClearing, isHistoryLoading, isLoading, runId]);

  const sendMessage = (content: string) => {
    const trimmed = content.trim();
    if (!trimmed || isLoading || isHistoryLoading || isClearing) {
      return;
    }

    const userMessage = { role: "user" as const, content: trimmed };
    const nextHistory = [...history, userMessage];
    const abortController = new AbortController();

    activeAbortControllerRef.current = abortController;
    setHistory(nextHistory);
    setRerunnableAssistantIndex(null);
    setIsPendingReplySuppressed(false);
    setIsLoading(true);

    void chatWithTrace(runId, trimmed, history, abortController.signal)
      .then(({ history: responseHistory, edits_applied }) => {
        if (activeAbortControllerRef.current === abortController) {
          setHistory(responseHistory);
          setRerunnableAssistantIndex(edits_applied ? findLastAssistantIndex(responseHistory) : null);
        }
      })
      .catch((error) => {
        if (
          (error instanceof Error && error.name === "AbortError")
          || (error instanceof Error && error.message === "Trace chat canceled")
        ) {
          return;
        }

        const detail = error instanceof Error && error.message
          ? error.message
          : "could not reach the chat backend.";
        const errorMessage = detail.startsWith("Error:") ? detail : `Error: ${detail}`;
        if (activeAbortControllerRef.current === abortController) {
          setHistory([...nextHistory, { role: "assistant", content: errorMessage }]);
          setRerunnableAssistantIndex(null);
        }
      })
      .finally(() => {
        clearActiveRequest(abortController);
      });
  };

  const stopMessage = () => {
    const abortController = activeAbortControllerRef.current;
    if (!abortController) {
      return;
    }

    if (lastMessage?.role === "user") {
      setIsPendingReplySuppressed(true);
    }

    abortController.abort();
    clearActiveRequest(abortController);
    void abortTraceChat(runId).catch((error) => {
      console.error("Failed to abort trace chat:", error);
    });
  };

  const clearHistory = async () => {
    if (isLoading || isHistoryLoading || isClearing) {
      return;
    }

    const previousHistory = history;
    const previousRerunnableAssistantIndex = rerunnableAssistantIndex;

    setHistory([]);
    setRerunnableAssistantIndex(null);
    setIsPendingReplySuppressed(false);
    setIsClearing(true);
    try {
      await clearTraceChatHistory(runId);
    } catch (error) {
      console.error("Failed to clear trace chat history:", error);
      setHistory(previousHistory);
      setRerunnableAssistantIndex(previousRerunnableAssistantIndex);
    } finally {
      setIsClearing(false);
    }
  };

  const rerunAssistantMessage = async (messageIndex: number) => {
    setRerunnableAssistantIndex((current) => current === messageIndex ? null : current);
    await restartRun(runId);
  };

  return {
    clearHistory,
    history,
    isClearing,
    isHistoryLoading,
    isLoading,
    rerunnableAssistantIndex,
    rerunAssistantMessage,
    sendMessage,
    stopMessage,
  };
}
