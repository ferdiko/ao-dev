import { useState, useRef, useEffect } from "react";
import { Sparkles, Send, PanelRight, Loader2, RotateCcw } from "lucide-react";
import { chatWithTrace, restartRun } from "../api";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  editsApplied?: boolean;
}

export function TraceChat({ sessionId, onCollapse }: { sessionId: string; onCollapse?: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

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
          {messages.map((m) => (
            <div key={m.id} className={`trace-chat-msg trace-chat-msg-${m.role}`}>
              <div className="trace-chat-msg-content">{m.content}</div>
              {m.editsApplied && (
                <button className="trace-chat-rerun-btn" onClick={() => void handleRerun(m.id)}>
                  <RotateCcw size={12} /> Re-run
                </button>
              )}
            </div>
          ))}
          {isLoading && (
            <div className="trace-chat-msg trace-chat-msg-assistant">
              <div className="trace-chat-msg-content trace-chat-thinking">
                <Loader2 size={12} className="fa-spinner" /> Thinking…
              </div>
            </div>
          )}
        </div>
        <div className="trace-chat-input-row">
          <input
            className="trace-chat-input"
            type="text"
            placeholder="Ask about this trace…"
            value={input}
            disabled={isLoading}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void handleSend(); }}
          />
          <button className="trace-chat-send" onClick={() => void handleSend()} disabled={!input.trim() || isLoading}>
            {isLoading ? <Loader2 size={13} className="fa-spinner" /> : <Send size={13} />}
          </button>
        </div>
      </div>
    </div>
  );
}
