import { useState, useCallback, useRef, useEffect } from "react";
import { Sparkles, Send, Loader2 } from "lucide-react";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export function TraceChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: "welcome", role: "assistant", content: "Ask me anything about this trace. I can help you understand the dataflow, identify issues, or suggest improvements." },
  ]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = useCallback(() => {
    if (!input.trim() || thinking) return;
    const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: "user", content: input.trim() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setThinking(true);

    setTimeout(() => {
      const responses = [
        "Looking at this trace, the dataflow shows a typical chain pattern where each LLM call builds on the previous output. The edge detection confirms content is being passed through correctly.",
        "I can see the input to this node contains content from the previous node's output. The string matching algorithm detected a coverage of ~92%, which is well above the threshold.",
        "This node's latency is higher than expected. Consider checking if the model parameter or token count could be optimized. The prompt contains repeated context that could be trimmed.",
        "The output from this node appears well-formed. If you're seeing unexpected behavior downstream, try editing the output to isolate which part of the response is causing issues.",
      ];
      const reply: ChatMessage = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: responses[Math.floor(Math.random() * responses.length)],
      };
      setMessages((prev) => [...prev, reply]);
      setThinking(false);
    }, 1500);
  }, [input, thinking]);

  return (
    <div className="trace-chat">
      <div className="trace-chat-header">
        <div className="trace-chat-header-title">
          <div className="trace-chat-title">
            <Sparkles size={13} />
            <span>Sovara Trace Analysis</span>
          </div>
        </div>
      </div>
      <div className="trace-chat-messages" ref={scrollRef}>
        {messages.map((m) => (
          <div key={m.id} className={`trace-chat-msg trace-chat-msg-${m.role}`}>
            <div className="trace-chat-msg-content">{m.content}</div>
          </div>
        ))}
        {thinking && (
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
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleSend(); }}
        />
        <button className="trace-chat-send" onClick={handleSend} disabled={!input.trim() || thinking}>
          <Send size={13} />
        </button>
      </div>
    </div>
  );
}
