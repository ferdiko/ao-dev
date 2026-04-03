import { cloneElement, isValidElement, type ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

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

export function TraceChatMessageContent({
  content,
  onStepLabelClick,
}: {
  content: string;
  onStepLabelClick?: (nodeId: string) => void;
}) {
  return (
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
      {content}
    </Markdown>
  );
}
