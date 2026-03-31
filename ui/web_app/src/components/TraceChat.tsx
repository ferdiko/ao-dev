import { cloneElement, isValidElement, useEffect, useRef, useState, type ReactNode } from "react";
import { Sparkles, Send, PanelRight, Loader2, RotateCcw, Square } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  abortTraceChat,
  chatWithTrace,
  clearTraceChatHistory,
  fetchTraceChatHistory,
  restartRun,
  type TraceChatHistoryMessage,
} from "../api";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  editsApplied?: boolean;
}

const STEP_LABEL_RE = /\b(steps?\s+\d{1,3}(?:(?:\s*[–-]\s*|\s+to\s+)\d{1,3}|(?:\s*,\s*(?:and\s+)?|\s+and\s+|\s*&\s*)\d{1,3})*)\b/gi;

function getPrimaryStepNodeId(label: string): string | null {
  const firstStepNumber = label.match(/\d{1,3}/);
  return firstStepNumber ? firstStepNumber[0] : null;
}

function highlightStepLabels(node: ReactNode, onStepLabelClick?: (nodeId: string) => void): ReactNode {
  if (typeof node === "string") {
    const parts = node.split(STEP_LABEL_RE);
    if (parts.length === 1) {
      return node;
    }

    return parts.map((part, index) => (
      index % 2 === 1 ? (
        <span
          key={`${part}-${index}`}
          className={`trace-chat-step-label${onStepLabelClick ? " clickable" : ""}`}
          onClick={() => {
            const nodeId = getPrimaryStepNodeId(part);
            if (nodeId && onStepLabelClick) {
              onStepLabelClick(nodeId);
            }
          }}
          title={onStepLabelClick ? "Focus this step in the graph" : undefined}
        >
          {part}
        </span>
      ) : part
    ));
  }

  if (Array.isArray(node)) {
    return node.map((child) => highlightStepLabels(child, onStepLabelClick));
  }

  if (isValidElement<{ children?: ReactNode }>(node) && node.props.children) {
    return cloneElement(node, {
      children: highlightStepLabels(node.props.children, onStepLabelClick),
    });
  }

  return node;
}

function buildPersistedHistory(messages: ChatMessage[]): TraceChatHistoryMessage[] {
  return messages.map(({ role, content }) => ({ role, content }));
}

function hydrateMessages(
  history: TraceChatHistoryMessage[],
  options?: { editsApplied?: boolean },
): ChatMessage[] {
  let lastAssistantIndex = -1;
  if (options?.editsApplied) {
    for (let index = history.length - 1; index >= 0; index -= 1) {
      if (history[index]?.role === "assistant") {
        lastAssistantIndex = index;
        break;
      }
    }
  }

  return history.map((message, index) => ({
    id: `h-${index}-${message.role}`,
    role: message.role,
    content: message.content,
    editsApplied: options?.editsApplied && index === lastAssistantIndex ? true : undefined,
  }));
}

function historiesMatch(messages: ChatMessage[], history: TraceChatHistoryMessage[]): boolean {
  if (messages.length !== history.length) {
    return false;
  }
  return messages.every((message, index) => (
    message.role === history[index]?.role
    && message.content === history[index]?.content
  ));
}

const PENDING_HISTORY_POLL_MS = 1000;
const PENDING_HISTORY_POLL_TIMEOUT_MS = 120000;

export function TraceChat({
  runId,
  onCollapse,
  onStepLabelClick,
}: {
  runId: string;
  onCollapse?: () => void;
  onStepLabelClick?: (nodeId: string) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [activeRequestId, setActiveRequestId] = useState<number | null>(null);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const isMountedRef = useRef(true);
  const activeAbortControllerRef = useRef<AbortController | null>(null);
  const requestCounterRef = useRef(0);
  const activeRequestIdRef = useRef<number | null>(null);
  const suppressedPendingUserMessageIdRef = useRef<string | null>(null);
  const lastMessage = messages[messages.length - 1];
  const hasPendingPersistedReply = (
    lastMessage?.role === "user"
    && suppressedPendingUserMessageIdRef.current !== lastMessage.id
  );
  const isLoading = activeRequestId !== null;

  const clearActiveRequest = () => {
    activeAbortControllerRef.current = null;
    activeRequestIdRef.current = null;
    if (isMountedRef.current) {
      setActiveRequestId(null);
    }
  };

  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    const textarea = inputRef.current;
    if (!textarea) {
      return;
    }

    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }, [input]);

  useEffect(() => {
    let cancelled = false;
    setMessages([]);
    setInput("");
    setIsHistoryLoading(true);
    suppressedPendingUserMessageIdRef.current = null;

    fetchTraceChatHistory(runId)
      .then((history) => {
        if (!cancelled) {
          setMessages(hydrateMessages(history));
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error("Failed to load trace chat history:", error);
          setMessages([]);
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
    if (isHistoryLoading || isClearing) {
      return;
    }
    if (!hasPendingPersistedReply) {
      suppressedPendingUserMessageIdRef.current = null;
      return;
    }

    let cancelled = false;
    const deadline = Date.now() + PENDING_HISTORY_POLL_TIMEOUT_MS;

    const poll = async () => {
      while (!cancelled && Date.now() < deadline) {
        await new Promise((resolve) => {
          setTimeout(resolve, PENDING_HISTORY_POLL_MS);
        });
        if (cancelled) {
          return;
        }
        try {
          const history = await fetchTraceChatHistory(runId);
          if (cancelled) {
            return;
          }
          if (!historiesMatch(messages, history)) {
            setMessages(hydrateMessages(history));
            if (
              activeRequestIdRef.current !== null
              && history[history.length - 1]?.role === "assistant"
            ) {
              clearActiveRequest();
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
  }, [hasPendingPersistedReply, isClearing, isHistoryLoading, messages, runId]);

  const handleSend = async () => {
    if (!input.trim() || isLoading || isHistoryLoading || isClearing) return;
    const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: "user", content: input.trim() };
    const history = buildPersistedHistory(messages);
    const messagesWithUser = [...messages, userMsg];
    const abortController = new AbortController();
    const requestId = requestCounterRef.current + 1;
    requestCounterRef.current = requestId;
    activeAbortControllerRef.current = abortController;
    activeRequestIdRef.current = requestId;
    suppressedPendingUserMessageIdRef.current = null;
    setMessages(messagesWithUser);
    setInput("");
    setActiveRequestId(requestId);
    try {
      const { history: nextHistory, edits_applied } = await chatWithTrace(
        runId,
        userMsg.content,
        history,
        abortController.signal,
      );
      if (isMountedRef.current && activeRequestIdRef.current === requestId) {
        setMessages(hydrateMessages(nextHistory, { editsApplied: edits_applied }));
      }
    } catch (error) {
      if (
        (error instanceof Error && error.name === "AbortError")
        || (error instanceof Error && error.message === "Trace chat canceled")
      ) {
        return;
      }
      const detail = error instanceof Error && error.message
        ? error.message
        : "could not reach the chat backend.";
      const content = detail.startsWith("Error:") ? detail : `Error: ${detail}`;
      if (isMountedRef.current && activeRequestIdRef.current === requestId) {
        setMessages([...messagesWithUser, { id: `e-${Date.now()}`, role: "assistant", content }]);
      }
    } finally {
      if (activeRequestIdRef.current === requestId) {
        clearActiveRequest();
      }
    }
  };

  const handleStop = () => {
    if (activeRequestIdRef.current === null) return;
    const lastMessage = messages[messages.length - 1];
    if (lastMessage?.role === "user") {
      suppressedPendingUserMessageIdRef.current = lastMessage.id;
    }
    activeAbortControllerRef.current?.abort();
    clearActiveRequest();
    void abortTraceChat(runId).catch((error) => {
      console.error("Failed to abort trace chat:", error);
    });
  };

  const handleClear = async () => {
    if (isLoading || isHistoryLoading || isClearing) return;
    const previousMessages = messages;
    suppressedPendingUserMessageIdRef.current = null;
    setMessages([]);
    setInput("");
    setIsClearing(true);
    try {
      await clearTraceChatHistory(runId);
    } catch (error) {
      console.error("Failed to clear trace chat history:", error);
      setMessages(previousMessages);
    } finally {
      setIsClearing(false);
    }
  };

  const handleRerun = async (msgId: string) => {
    setMessages((prev) => prev.map((m) => m.id === msgId ? { ...m, editsApplied: false } : m));
    await restartRun(runId);
  };

  return (
    <div className="trace-chat">
      <div className="trace-chat-header">
        <div className="trace-chat-header-title">
          <div className="trace-chat-title">
            <Sparkles size={13} />
            <span>Trace Chat</span>
          </div>
          <div className="trace-chat-header-actions">
            <button
              className="run-rerun-btn run-reset-btn trace-chat-clear-btn"
              onClick={() => void handleClear()}
              disabled={isHistoryLoading || isLoading || isClearing || messages.length === 0}
              title="Clear persisted chat history for this run"
            >
              {isClearing ? "Clearing…" : "Clear Chat"}
            </button>
            {onCollapse && (
              <button className="trace-chat-collapse" onClick={onCollapse} title="Collapse chat">
                <PanelRight size={14} />
              </button>
            )}
          </div>
        </div>
      </div>
      <div className="trace-chat-body">
        <div className="trace-chat-messages" ref={scrollRef}>
          {messages.map((m, i) => {
            const isLastAssistant = m.role === "assistant" && !messages.slice(i + 1).some((n) => n.role === "assistant");
            return (
              <div key={m.id} className={`trace-chat-msg trace-chat-msg-${m.role}`}>
                <div className="trace-chat-msg-content">
                  {m.role === "assistant" ? (
                    <Markdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        p: ({ children, ...props }) => <p {...props}>{highlightStepLabels(children, onStepLabelClick)}</p>,
                        li: ({ children, ...props }) => <li {...props}>{highlightStepLabels(children, onStepLabelClick)}</li>,
                        blockquote: ({ children, ...props }) => <blockquote {...props}>{highlightStepLabels(children, onStepLabelClick)}</blockquote>,
                        td: ({ children, ...props }) => <td {...props}>{highlightStepLabels(children, onStepLabelClick)}</td>,
                        th: ({ children, ...props }) => <th {...props}>{highlightStepLabels(children, onStepLabelClick)}</th>,
                      }}
                    >
                      {m.content}
                    </Markdown>
                  ) : m.content}
                  {m.editsApplied && isLastAssistant && (
                    <button className="trace-chat-rerun-btn" onClick={() => void handleRerun(m.id)}>
                      <RotateCcw size={12} /> Re-run with changes
                    </button>
                  )}
                </div>
              </div>
            );
          })}
          {isHistoryLoading && (
            <div className="trace-chat-msg trace-chat-msg-assistant">
              <div className="trace-chat-msg-content trace-chat-thinking">
                <Loader2 size={12} className="fa-spinner" /> Loading chat…
              </div>
            </div>
          )}
          {isLoading && (
            <div className="trace-chat-msg trace-chat-msg-assistant">
              <div className="trace-chat-msg-content trace-chat-thinking">
                <Loader2 size={12} className="fa-spinner" /> Thinking…
              </div>
            </div>
          )}
        </div>
        <div className="trace-chat-input-row">
          <textarea
            ref={inputRef}
            className="trace-chat-input"
            placeholder="Ask about this trace…"
            value={input}
            disabled={isLoading || isHistoryLoading || isClearing}
            onChange={(e) => setInput(e.target.value)}
            rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
            }}
          />
          <button
            className="trace-chat-send"
            onClick={() => void (isLoading ? handleStop() : handleSend())}
            disabled={isHistoryLoading || isClearing || (!isLoading && !input.trim())}
            title={isLoading ? "Stop trace chat" : "Send message"}
          >
            {isLoading ? <Square size={13} /> : <Send size={13} />}
          </button>
        </div>
      </div>
    </div>
  );
}
