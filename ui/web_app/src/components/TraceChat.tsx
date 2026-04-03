import { useEffect, useRef, useState } from "react";
import { Sparkles, Loader2, RotateCcw, PanelRight } from "lucide-react";
import { TraceChatComposer } from "./TraceChatComposer";
import { TraceChatMessageContent } from "./TraceChatMessageContent";
import { useTraceChatSession } from "../hooks/useTraceChatSession";

export function TraceChat({
  runId,
  onCollapse,
  onStepLabelClick,
}: {
  runId: string;
  onCollapse?: () => void;
  onStepLabelClick?: (nodeId: string) => void;
}) {
  const [composerResetVersion, setComposerResetVersion] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const {
    clearHistory,
    history,
    isClearing,
    isHistoryLoading,
    isLoading,
    rerunnableAssistantIndex,
    rerunAssistantMessage,
    sendMessage,
    stopMessage,
  } = useTraceChatSession(runId);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history, isHistoryLoading, isLoading]);

  const handleSend = (content: string) => {
    sendMessage(content);
  };

  const handleClear = () => {
    setComposerResetVersion((version) => version + 1);
    void clearHistory();
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
              onClick={handleClear}
              disabled={isHistoryLoading || isLoading || isClearing || history.length === 0}
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
          {history.map((message, index) => (
            <div key={`${index}-${message.role}`} className={`trace-chat-msg trace-chat-msg-${message.role}`}>
              <div className="trace-chat-msg-content">
                {message.role === "assistant" ? (
                  <TraceChatMessageContent content={message.content} onStepLabelClick={onStepLabelClick} />
                ) : (
                  message.content
                )}
                {index === rerunnableAssistantIndex && (
                  <button className="trace-chat-rerun-btn" onClick={() => void rerunAssistantMessage(index)}>
                    <RotateCcw size={12} /> Re-run with changes
                  </button>
                )}
              </div>
            </div>
          ))}
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
        <TraceChatComposer
          key={`${runId}:${composerResetVersion}`}
          isLoading={isLoading}
          disabled={isHistoryLoading || isClearing}
          onSend={handleSend}
          onStop={stopMessage}
        />
      </div>
    </div>
  );
}
