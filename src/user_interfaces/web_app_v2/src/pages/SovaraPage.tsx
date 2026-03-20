import { useState, useCallback, useRef, useEffect } from "react";
import { useParams } from "react-router-dom";
import {
  Sparkles, Send, Loader2, Check, X,
  ChevronDown,
  Shield, Zap,
} from "lucide-react";
import { Breadcrumb } from "../components/Breadcrumb";
import { mockProjects } from "../data/mock";


import logoWithSymbol from "../assets/logo_with_symbol.png";

// ── Types ──────────────────────────────────────────────

type EditMode = "ask" | "auto";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  proposal?: {
    type: "create_prior";
    title: string;
    description: string;
    accepted?: boolean;
  };
}

// ── Mock conversation ──────────────────────────────────

const mockConversation: ChatMessage[] = [
  {
    id: "m-1", role: "user",
    content: "Why does SQL validation keep failing on queries with JOINs?",
  },
  {
    id: "m-2", role: "assistant",
    content: "I looked at the last 20 runs and found that 6 out of 8 SQL validation failures involve queries with 3+ JOINs. The issue is that the SQL Generation node doesn't consistently alias subqueries, which causes ambiguous column references when the validator checks the query.\n\nRuns affected: Run 41, 43, 44, 46, 48, 49.",
  },
  {
    id: "m-3", role: "user",
    content: "Can you create a prior so the SQL generation always aliases subqueries?",
  },
  {
    id: "m-4", role: "assistant",
    content: "I'd like to create the following prior. Should I go ahead?",
    proposal: {
      type: "create_prior",
      title: "Always alias subqueries in SQL generation",
      description: "When generating SQL queries that contain subqueries or CTEs, always assign explicit aliases to each subquery (e.g., `AS sq1`, `AS cte_results`). This prevents ambiguous column references when the query involves multiple JOINs.",
    },
  },
];

// ── Main Component ─────────────────────────────────────

export function SovaraPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const project = mockProjects.find((p) => p.id === projectId);

  // Chat state
  const [messages, setMessages] = useState<ChatMessage[]>(mockConversation);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [editMode, setEditMode] = useState<EditMode>("ask");
  const [modeDropdownOpen, setModeDropdownOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const modeRef = useRef<HTMLDivElement>(null);

  // Close mode dropdown on outside click
  useEffect(() => {
    if (!modeDropdownOpen) return;
    function handleClick(e: MouseEvent) {
      if (modeRef.current && !modeRef.current.contains(e.target as Node)) {
        setModeDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [modeDropdownOpen]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const hasConversation = messages.length > 0 || thinking;

  const handleSend = useCallback(() => {
    if (!input.trim() || thinking) return;
    const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: "user", content: input.trim() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setThinking(true);

    setTimeout(() => {
      const responses = [
        "I analyzed your recent runs and noticed a pattern: the SQL generation step tends to produce longer queries when the user question mentions aggregations. This might explain the increased latency in runs 45–49.",
        "Looking at the failure patterns across your experiments, the most common issue is that the Answer Synthesis node receives truncated query results. I'd recommend checking the token limit on the Execute Query output.",
        "Based on the priors you've configured, I can see that the schema retrieval step is performing well — it consistently returns the right tables. The bottleneck appears to be in SQL validation, where about 15% of generated queries fail the first check.",
        "I've reviewed the dataflow across your last 10 runs. The edge detection shows strong content propagation from Schema Retrieval through to Answer Synthesis. No orphaned nodes or broken chains detected.",
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

  const handleProposalAction = useCallback((msgId: string, accepted: boolean) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId && m.proposal
          ? { ...m, proposal: { ...m.proposal, accepted } }
          : m,
      ),
    );
    if (accepted) {
      const followUp: ChatMessage = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: 'Done — I\'ve created the prior "Always alias subqueries in SQL generation" and applied it to the SQL Generation node. It will take effect on the next run.',
      };
      setTimeout(() => setMessages((prev) => [...prev, followUp]), 400);
    }
  }, []);

  if (!project) return <div>Project not found</div>;

  return (
    <div className="page-wrapper">
      <Breadcrumb
        items={[
          { label: "Organization", to: "/" },
          { label: "Sovara" },
        ]}
      />

      <div className="sovara-page">
        {/* ── Chat ── */}
        <div className="sovara-chat-panel">
          {!hasConversation ? (
            <div className="sovara-empty">
              <img src={logoWithSymbol} alt="Sovara" className="sovara-empty-logo" />
              <div className="sovara-empty-title">Sovara</div>
              <div className="sovara-empty-subtitle">
                Ask me anything about your runs, priors, or agent performance.
              </div>
              <div className="sovara-empty-input-row">
                <input
                  ref={inputRef}
                  className="sovara-input"
                  type="text"
                  placeholder="Ask Sovara…"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleSend(); }}
                />
                <button className="sovara-send" onClick={handleSend} disabled={!input.trim()}>
                  <Send size={15} />
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="sovara-messages" ref={scrollRef}>
                {messages.map((m) => (
                  <div key={m.id} className={`sovara-msg sovara-msg-${m.role}`}>
                    {m.role === "assistant" && (
                      <div className="sovara-msg-avatar">
                        <Sparkles size={14} />
                      </div>
                    )}
                    <div className="sovara-msg-body">
                      <div className="sovara-msg-content">{m.content}</div>
                      {m.proposal && (
                        <div className={`sovara-proposal${m.proposal.accepted === true ? " accepted" : m.proposal.accepted === false ? " rejected" : ""}`}>
                          <div className="sovara-proposal-header">
                            <span className="sovara-proposal-type">Create Prior</span>
                          </div>
                          <div className="sovara-proposal-title">{m.proposal.title}</div>
                          <div className="sovara-proposal-desc">{m.proposal.description}</div>
                          {m.proposal.accepted === undefined && (
                            <div className="sovara-proposal-actions">
                              <button className="sovara-proposal-accept" onClick={() => handleProposalAction(m.id, true)}>
                                <Check size={13} /> Accept
                              </button>
                              <button className="sovara-proposal-reject" onClick={() => handleProposalAction(m.id, false)}>
                                <X size={13} /> Reject
                              </button>
                            </div>
                          )}
                          {m.proposal.accepted === true && (
                            <div className="sovara-proposal-status sovara-proposal-status-accepted">
                              <Check size={12} /> Accepted
                            </div>
                          )}
                          {m.proposal.accepted === false && (
                            <div className="sovara-proposal-status sovara-proposal-status-rejected">
                              <X size={12} /> Rejected
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {thinking && (
                  <div className="sovara-msg sovara-msg-assistant">
                    <div className="sovara-msg-avatar"><Sparkles size={14} /></div>
                    <div className="sovara-msg-body">
                      <div className="sovara-msg-content sovara-thinking">
                        <Loader2 size={14} className="fa-spinner" /> Thinking…
                      </div>
                    </div>
                  </div>
                )}
              </div>
              <div className="sovara-bottom-input">
                <div className="sovara-mode-selector" ref={modeRef}>
                  <button className="sovara-mode-btn" onClick={() => setModeDropdownOpen(!modeDropdownOpen)}>
                    {editMode === "ask" ? <Shield size={13} /> : <Zap size={13} />}
                    {editMode === "ask" ? "Ask" : "Auto"}
                    <ChevronDown size={11} />
                  </button>
                  {modeDropdownOpen && (
                    <div className="sovara-mode-dropdown">
                      <button
                        className={`sovara-mode-option${editMode === "ask" ? " active" : ""}`}
                        onClick={() => { setEditMode("ask"); setModeDropdownOpen(false); }}
                      >
                        <Shield size={13} />
                        <div>
                          <div className="sovara-mode-option-label">Ask mode</div>
                          <div className="sovara-mode-option-desc">Sovara asks before making changes</div>
                        </div>
                      </button>
                      <button
                        className={`sovara-mode-option${editMode === "auto" ? " active" : ""}`}
                        onClick={() => { setEditMode("auto"); setModeDropdownOpen(false); }}
                      >
                        <Zap size={13} />
                        <div>
                          <div className="sovara-mode-option-label">Auto mode</div>
                          <div className="sovara-mode-option-desc">Sovara applies changes automatically</div>
                        </div>
                      </button>
                    </div>
                  )}
                </div>
                <input
                  className="sovara-input"
                  type="text"
                  placeholder="Ask Sovara…"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleSend(); }}
                />
                <button className="sovara-send" onClick={handleSend} disabled={!input.trim() || thinking}>
                  <Send size={15} />
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
