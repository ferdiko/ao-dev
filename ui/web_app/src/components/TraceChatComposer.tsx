import { useEffect, useRef, useState } from "react";
import { Send, Square } from "lucide-react";

export function TraceChatComposer({
  isLoading,
  disabled,
  onSend,
  onStop,
}: {
  isLoading: boolean;
  disabled: boolean;
  onSend: (content: string) => void;
  onStop: () => void;
}) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const textarea = inputRef.current;
    if (!textarea) {
      return;
    }

    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }, [value]);

  return (
    <div className="trace-chat-input-row">
      <textarea
        ref={inputRef}
        className="trace-chat-input"
        placeholder="Ask about this trace…"
        value={value}
        disabled={isLoading || disabled}
        onChange={(e) => setValue(e.target.value)}
        rows={1}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (isLoading) {
              onStop();
            } else if (!disabled && value.trim()) {
              onSend(value.trim());
              setValue("");
            }
          }
        }}
      />
      <button
        className="trace-chat-send"
        onClick={() => {
          if (isLoading) {
            onStop();
          } else if (value.trim()) {
            onSend(value.trim());
            setValue("");
          }
        }}
        disabled={disabled || (!isLoading && !value.trim())}
        title={isLoading ? "Stop trace chat" : "Send message"}
      >
        {isLoading ? <Square size={13} /> : <Send size={13} />}
      </button>
    </div>
  );
}
