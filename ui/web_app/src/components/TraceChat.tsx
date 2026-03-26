import { cloneElement, isValidElement, useEffect, useRef, useState, type ReactNode } from "react";
import { Sparkles, Send, PanelRight, Loader2, RotateCcw } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chatWithTrace, restartRun } from "../api";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  editsApplied?: boolean;
}

const STEP_LABEL_RE = /\b(steps?\s+\d{1,3}(?:(?:\s*[–-]\s*|\s+to\s+|\s+and\s+)\d{1,3}|(?:\s*,\s*\d{1,3})+)?)\b/gi;

function getPrimaryStepNodeId(label: string): string | null {
  const firstStepNumber = label.match(/\d{1,3}/);
  return firstStepNumber ? `step ${firstStepNumber[0]}` : null;
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

export function TraceChat({
  sessionId,
  onCollapse,
  onStepLabelClick,
}: {
  sessionId: string;
  onCollapse?: () => void;
  onStepLabelClick?: (nodeId: string) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

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

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: "user", content: input.trim() };
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsLoading(true);
    try {
      const { answer, edits_applied } = await chatWithTrace(sessionId, userMsg.content, history);
      setMessages((prev) => [...prev, { id: `a-${Date.now()}`, role: "assistant", content: answer, editsApplied: edits_applied }]);
    } catch {
      setMessages((prev) => [...prev, { id: `e-${Date.now()}`, role: "assistant", content: "Error: could not reach the chat backend." }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRerun = async (msgId: string) => {
    setMessages((prev) => prev.map((m) => m.id === msgId ? { ...m, editsApplied: false } : m));
    await restartRun(sessionId);
  };

  return (
    <div className="trace-chat">
      <div className="trace-chat-header">
        <div className="trace-chat-header-title">
          <div className="trace-chat-title">
            <Sparkles size={13} />
            <span>Trace Chat</span>
          </div>
          {onCollapse && (
            <button className="trace-chat-collapse" onClick={onCollapse} title="Collapse chat">
              <PanelRight size={14} />
            </button>
          )}
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
            disabled={isLoading}
            onChange={(e) => setInput(e.target.value)}
            rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
            }}
          />
          <button className="trace-chat-send" onClick={() => void handleSend()} disabled={!input.trim() || isLoading}>
            {isLoading ? <Loader2 size={13} className="fa-spinner" /> : <Send size={13} />}
          </button>
        </div>
      </div>
    </div>
  );
}
