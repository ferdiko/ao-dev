import { useState, useRef, useEffect } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Sparkles, Send, PanelRight } from "lucide-react";
import { type PrismStyleMap, withTransparentPrismTheme } from "@sovara/shared-components/utils/prismTheme";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

type MarkdownCodeProps = {
  children?: React.ReactNode;
  className?: string;
};

const CHAT_LANG_DISPLAY: Record<string, string> = {
  markdown: "Markdown",
  md: "Markdown",
  sql: "SQL",
  json: "JSON",
  python: "Python",
  rust: "Rust",
  javascript: "JavaScript",
  typescript: "TypeScript",
  tsx: "TSX",
  go: "Go",
  html: "HTML",
  bash: "Bash",
  css: "CSS",
  yaml: "YAML",
  xml: "XML",
  text: "Text",
};

const STRONG_MARKDOWN_PATTERNS = [
  /^#{1,6}\s/m,
  /^[-*+]\s/m,
  /^\d+\.\s/m,
  /^>\s/m,
  /\|.+\|/,
  /\[[^\]]+\]\([^)]+\)/,
  /```[\s\S]*```/,
];

const chatSyntaxTheme = withTransparentPrismTheme(oneLight as unknown as PrismStyleMap, {
  fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace',
  fontSize: "12.5px",
  lineHeight: "1.6",
});

function inferCodeLanguage(value: string): string {
  const trimmed = value.trim();

  if (/^\s*SELECT\b[\s\S]*\bFROM\b/i.test(trimmed) || /\bGROUP BY\b/i.test(trimmed)) {
    return "sql";
  }

  if (/^\s*(def |from |import )/m.test(trimmed) || /\blambda\b/.test(trimmed)) {
    return "python";
  }

  if (/^\s*package\s+\w+/m.test(trimmed) && /\bfunc\s+\w+\(/.test(trimmed)) {
    return "go";
  }

  if (/^\s*#!\/bin\/(ba)?sh/m.test(trimmed) || /(^|\n)\s*(echo|export|cd|grep|uv|python3?)\b/.test(trimmed)) {
    return "bash";
  }

  if (/<[A-Za-z]/.test(trimmed) && /\{[^}]*[:=][^}]*\}/.test(trimmed)) {
    return "tsx";
  }

  if (/\binterface\s+\w+/.test(trimmed) || /\btype\s+\w+\s*=/.test(trimmed) || /\bexport\s+function\b/.test(trimmed)) {
    return "typescript";
  }

  if (/\bfunction\b/.test(trimmed) || /\bconsole\./.test(trimmed) || /=>/.test(trimmed)) {
    return "javascript";
  }

  if (/^<([A-Za-z_][\w:.-]*)(\s+[^<>]*)?>[\s\S]*<\/\1>$|^<([A-Za-z_][\w:.-]*)(\s+[^<>]*)?\/>$/.test(trimmed)) {
    return "xml";
  }

  return "text";
}

function looksLikeMarkdown(value: string): boolean {
  if (STRONG_MARKDOWN_PATTERNS.some((pattern) => pattern.test(value))) {
    return true;
  }

  const inlineCodeMatches = value.match(/`[^`\n]+`/g) || [];
  return inlineCodeMatches.length >= 2 && value.includes("\n");
}

function inferFencedSnippetLanguage(value: string): string {
  if (looksLikeMarkdown(value)) {
    return "markdown";
  }

  return inferCodeLanguage(value);
}

function ChatCodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="trace-chat-code-block">
      <div className="trace-chat-code-header">
        <span className="trace-chat-code-lang">{CHAT_LANG_DISPLAY[language] ?? language}</span>
        <button
          className="trace-chat-code-copy"
          onClick={(event) => {
            event.stopPropagation();
            handleCopy();
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <SyntaxHighlighter
        language={language}
        style={chatSyntaxTheme}
        customStyle={{
          padding: "12px 14px",
          borderRadius: 0,
          background: "transparent",
          fontFamily: '"SFMono-Regular","Menlo","Consolas",monospace',
          fontSize: "12.5px",
          lineHeight: "1.6",
        }}
        codeTagProps={{ style: { background: "transparent" } }}
        wrapLongLines
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}

function ChatMarkdown({ content }: { content: string }) {
  return (
    <div className="trace-chat-markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          code(props: MarkdownCodeProps) {
            const text = String(props.children ?? "").replace(/\n$/, "");
            const languageMatch = /language-([\w+-]+)/.exec(props.className || "");
            const isBlock = Boolean(languageMatch) || text.includes("\n");

            if (!isBlock) {
              return <code className="trace-chat-inline-code">{props.children}</code>;
            }

            return <ChatCodeBlock code={text} language={languageMatch?.[1] ?? inferFencedSnippetLanguage(text)} />;
          },
        }}
      >
        {content}
      </Markdown>
    </div>
  );
}

export function TraceChat({ onCollapse }: { onCollapse?: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
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
              <div className="trace-chat-msg-content">
                <ChatMarkdown content={m.content} />
              </div>
            </div>
          ))}
        </div>
        <div className="trace-chat-input-row">
          <textarea
            ref={inputRef}
            className="trace-chat-input"
            placeholder="Ask about this trace…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <button className="trace-chat-send" onClick={handleSend} disabled={!input.trim()}>
            <Send size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
