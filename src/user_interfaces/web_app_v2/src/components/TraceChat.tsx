import { useState, useRef, useEffect } from "react";
import { Sparkles, Send, PanelRight } from "lucide-react";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export function TraceChat({ onCollapse }: { onCollapse?: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = () => {
    if (!input.trim()) return;
    const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: "user", content: input.trim() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
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
            </div>
          ))}
        </div>
        <div className="trace-chat-input-row">
          <input
            className="trace-chat-input"
            type="text"
            placeholder="Ask about this trace…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSend(); }}
          />
          <button className="trace-chat-send" onClick={handleSend} disabled={!input.trim()}>
            <Send size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
