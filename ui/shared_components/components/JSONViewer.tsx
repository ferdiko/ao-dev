import React, { useState } from 'react';
import { parse, stringify } from 'lossless-json';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { detectDocument, formatFileSize, getDocumentKey, DetectedDocument } from '../utils/documentDetection';
import {
  classifyStringContent,
  getScalarTypeLabel,
  getStringPreview,
  getUniformObjectArrayColumns,
  isLosslessNumberValue,
  isRecord,
  shouldCollapseLongText,
  unwrapFencedCode,
  unwrapLosslessNumber,
} from '../utils/contentClassification';
import { useDocumentContext } from '../contexts/DocumentContext';

interface JSONViewerProps {
  data: any;
  isDarkTheme: boolean;
  depth?: number;
  onChange?: (newData: any) => void;
  onOpenDocument?: (doc: DetectedDocument) => void;
  searchQuery?: string;
  currentMatchIndex?: number;
  onMatchCountChange?: (count: number) => void;
  defaultViewMode?: ViewMode;
  hideViewToggle?: boolean;
  containerPadding?: string | number;
  containerBackgroundColor?: string;
}

interface BaseNodeProps {
  keyName: string | null;
  value: any;
  isDarkTheme: boolean;
  depth: number;
  path: string[];
  siblingData?: Record<string, unknown>;
  onChange?: (path: string[], newValue: any) => void;
  onOpenDocument?: (doc: DetectedDocument) => void;
  searchQuery?: string;
  currentMatchIndex?: number;
  matchIndexOffset?: number;
}

type ViewMode = 'pretty' | 'raw';
type CodeTokenType = 'plain' | 'comment' | 'string' | 'number' | 'boolean' | 'keyword' | 'property' | 'tag' | 'attribute' | 'variable';
type CodeToken = { type: CodeTokenType; text: string };

const MAX_PRETTY_DEPTH = 4;

function getViewerColors(isDarkTheme: boolean) {
  return {
    key: 'var(--vscode-symbolIcon-propertyForeground, #9cdcfe)',
    string: 'var(--vscode-debugTokenExpression-string, #ce9178)',
    number: 'var(--vscode-debugTokenExpression-number, #b5cea8)',
    boolean: 'var(--vscode-debugTokenExpression-boolean, #569cd6)',
    null: 'var(--vscode-debugTokenExpression-boolean, #569cd6)',
    keyword: 'var(--vscode-symbolIcon-keywordForeground, #c586c0)',
    comment: 'var(--vscode-descriptionForeground, #6a9955)',
    tag: 'var(--vscode-symbolIcon-classForeground, #4ec9b0)',
    attribute: 'var(--vscode-symbolIcon-propertyForeground, #9cdcfe)',
    variable: 'var(--vscode-symbolIcon-variableForeground, #9cdcfe)',
    bracket: 'var(--vscode-foreground)',
    background: 'var(--vscode-editor-background)',
    hoverBackground: 'var(--vscode-list-hoverBackground)',
    inputBackground: 'var(--vscode-input-background)',
    inputBorder: 'var(--vscode-input-border, var(--vscode-panel-border))',
    cardBackground: isDarkTheme ? '#1f2428' : '#fafbfc',
    nestedBackground: isDarkTheme ? '#171b20' : '#ffffff',
    mutedText: 'var(--vscode-descriptionForeground, #6e7781)',
    badgeBackground: isDarkTheme ? '#27313b' : '#edf2f7',
    badgeText: 'var(--vscode-foreground)',
    toolbarBackground: isDarkTheme ? '#20252b' : '#f3f4f6',
    toolbarActive: isDarkTheme ? '#0e639c' : '#dbeafe',
    toolbarActiveText: isDarkTheme ? '#ffffff' : '#0b3b75',
    tableStripe: isDarkTheme ? '#1a1f24' : '#f7f9fb',
    quoteBorder: isDarkTheme ? '#4b5563' : '#cbd5e1',
  };
}

function keyLabelFromPath(keyName: string | null): string {
  if (keyName === null) {
    return '';
  }

  return keyName.split('.').pop() || keyName;
}

function countMatches(text: string, query: string): number {
  if (!query || !text) {
    return 0;
  }

  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  let index = 0;
  let count = 0;

  while ((index = lowerText.indexOf(lowerQuery, index)) !== -1) {
    count += 1;
    index += lowerQuery.length;
  }

  return count;
}

function highlightText(
  text: string,
  query?: string,
  startIndex = 0,
  currentMatch = -1,
): { element: React.ReactNode; matchCount: number } {
  if (!query || !text) {
    return { element: text, matchCount: 0 };
  }

  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let matchIndex = startIndex;
  let matchCount = 0;

  let position = 0;
  while ((position = lowerText.indexOf(lowerQuery, lastIndex)) !== -1) {
    if (position > lastIndex) {
      parts.push(text.substring(lastIndex, position));
    }

    const isCurrentMatch = matchIndex === currentMatch;
    const matchText = text.substring(position, position + query.length);
    parts.push(
      <span
        key={`match-${matchIndex}-${position}`}
        data-match-index={matchIndex}
        style={{
          backgroundColor: isCurrentMatch ? '#f0a020' : '#ffff00',
          color: '#000000',
          borderRadius: '2px',
          padding: '0 1px',
        }}
      >
        {matchText}
      </span>,
    );

    matchIndex += 1;
    matchCount += 1;
    lastIndex = position + query.length;
  }

  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex));
  }

  return { element: parts.length > 0 ? <>{parts}</> : text, matchCount };
}

const TypeBadge: React.FC<{ label: string; isDarkTheme: boolean }> = ({ label, isDarkTheme }) => {
  const colors = getViewerColors(isDarkTheme);
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '1px 6px',
        borderRadius: '999px',
        border: `1px solid ${isDarkTheme ? 'rgba(110, 118, 129, 0.22)' : 'rgba(110, 118, 129, 0.14)'}`,
        backgroundColor: isDarkTheme ? 'rgba(110, 118, 129, 0.10)' : 'rgba(110, 118, 129, 0.06)',
        color: colors.badgeText,
        fontSize: '10px',
        lineHeight: '14px',
        fontWeight: 400,
        opacity: 0.88,
        fontFamily: 'var(--vscode-font-family, sans-serif)',
      }}
    >
      {label}
    </span>
  );
};

const ActionIconButton: React.FC<{
  title: string;
  icon: string | React.ReactNode;
  isDarkTheme: boolean;
  active?: boolean;
  onClick: () => void;
}> = ({ title, icon, isDarkTheme, active = false, onClick }) => (
  <button
    title={title}
    aria-label={title}
    onClick={onClick}
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: '20px',
      height: '20px',
      padding: 0,
      borderRadius: '999px',
      border: `1px solid ${
        active
          ? isDarkTheme
            ? 'rgba(127, 183, 255, 0.32)'
            : 'rgba(4, 81, 165, 0.24)'
          : isDarkTheme
            ? 'rgba(110, 118, 129, 0.22)'
            : 'rgba(110, 118, 129, 0.14)'
      }`,
      backgroundColor: active
        ? isDarkTheme
          ? 'rgba(127, 183, 255, 0.12)'
          : 'rgba(4, 81, 165, 0.08)'
        : isDarkTheme
          ? 'rgba(110, 118, 129, 0.08)'
          : 'rgba(110, 118, 129, 0.05)',
      color: active
        ? isDarkTheme
          ? '#7fb7ff'
          : '#0451a5'
        : 'var(--vscode-descriptionForeground, #6e7781)',
      cursor: 'pointer',
    }}
  >
    {typeof icon === 'string' ? <i className={`codicon ${icon}`} style={{ fontSize: '12px' }} /> : icon}
  </button>
);

const ViewerToggle: React.FC<{
  viewMode: ViewMode;
  onChange: (next: ViewMode) => void;
  isDarkTheme: boolean;
  editable: boolean;
}> = ({ viewMode, onChange, isDarkTheme, editable }) => {
  const colors = getViewerColors(isDarkTheme);

  const renderButton = (mode: ViewMode, label: string) => {
    const active = viewMode === mode;
    return (
      <button
        onClick={() => onChange(mode)}
        style={{
          border: 'none',
          backgroundColor: active ? colors.toolbarActive : 'transparent',
          color: active ? colors.toolbarActiveText : colors.badgeText,
          padding: '4px 10px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '12px',
          fontWeight: 600,
        }}
        title={mode === 'raw' && editable ? 'Raw mode is the editable view' : undefined}
      >
        {label}
      </button>
    );
  };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'flex-end',
        gap: '8px',
        marginBottom: '10px',
      }}
    >
      {editable && (
        <span
          style={{
            color: colors.mutedText,
            fontSize: '12px',
            fontFamily: 'var(--vscode-font-family, sans-serif)',
          }}
        >
          Raw mode is editable
        </span>
      )}
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '2px',
          padding: '2px',
          borderRadius: '8px',
          border: `1px solid ${colors.inputBorder}`,
          backgroundColor: colors.toolbarBackground,
        }}
      >
        {renderButton('pretty', 'Pretty')}
        {renderButton('raw', 'Raw')}
      </div>
    </div>
  );
};

const DocumentButton: React.FC<{
  doc: DetectedDocument;
  isDarkTheme: boolean;
  onOpenDocument?: (doc: DetectedDocument) => void;
}> = ({ doc, isDarkTheme, onOpenDocument }) => {
  const colors = getViewerColors(isDarkTheme);
  const { openedPaths } = useDocumentContext();
  const docKey = getDocumentKey(doc.data);
  const openedPath = openedPaths.get(docKey);

  const iconMap: Record<string, string> = {
    pdf: 'file-pdf',
    png: 'file-media',
    jpeg: 'file-media',
    gif: 'file-media',
    webp: 'file-media',
    docx: 'file',
    xlsx: 'file',
    pptx: 'file',
    zip: 'file-zip',
    unknown: 'file-binary',
  };

  const labelMap: Record<string, string> = {
    pdf: 'PDF',
    png: 'PNG',
    jpeg: 'JPEG',
    gif: 'GIF',
    webp: 'WebP',
    docx: 'DOCX',
    xlsx: 'XLSX',
    pptx: 'PPTX',
    zip: 'file',
    unknown: 'file',
  };

  return (
    <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
      {onOpenDocument && (
        <button
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
            padding: '5px 10px',
            border: `1px solid ${colors.inputBorder}`,
            borderRadius: '6px',
            backgroundColor: colors.nestedBackground,
            color: colors.badgeText,
            cursor: 'pointer',
            fontFamily: 'var(--vscode-font-family, sans-serif)',
            fontSize: '13px',
          }}
          onClick={() => onOpenDocument(doc)}
        >
          <i className={`codicon codicon-${iconMap[doc.type]}`} />
          {` Open ${labelMap[doc.type]} (${formatFileSize(doc.size)})`}
        </button>
      )}
      {openedPath && (
        <span
          style={{
            fontFamily: 'var(--vscode-editor-font-family, monospace)',
            fontSize: '12px',
            color: colors.mutedText,
          }}
        >
          File available at {openedPath}
        </span>
      )}
    </div>
  );
};

const PrettyShell: React.FC<{
  label: string | null;
  badge?: string;
  isDarkTheme: boolean;
  depth: number;
  children: React.ReactNode;
  actions?: React.ReactNode;
  compact?: boolean;
}> = ({ label, badge, isDarkTheme, depth, children, actions, compact = false }) => {
  const colors = getViewerColors(isDarkTheme);
  const title = keyLabelFromPath(label);

  return (
    <div
      style={{
        marginBottom: '10px',
        marginLeft: depth > 0 ? '12px' : '0',
      }}
    >
      {(title || badge || actions) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '8px',
            marginBottom: '6px',
            fontFamily: 'var(--vscode-font-family, sans-serif)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            {title && (
              <span
                style={{
                  color: colors.key,
                  fontSize: '13px',
                  fontWeight: 600,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {title}
              </span>
            )}
            {badge && <TypeBadge label={badge} isDarkTheme={isDarkTheme} />}
          </div>
          {actions}
        </div>
      )}
      <div
        style={{
          border: `1px solid ${colors.inputBorder}`,
          borderRadius: '10px',
          backgroundColor: colors.cardBackground,
          padding: compact ? '8px 10px' : '12px',
        }}
      >
        {children}
      </div>
    </div>
  );
};

const ScalarBox: React.FC<{
  label: string | null;
  value: unknown;
  isDarkTheme: boolean;
  depth: number;
}> = ({ label, value, isDarkTheme, depth }) => {
  return (
    <PrettyShell
      label={label}
      badge={getScalarTypeLabel(value)}
      isDarkTheme={isDarkTheme}
      depth={depth}
      compact
    >
      <CompactScalarValue value={value} isDarkTheme={isDarkTheme} singleLine />
    </PrettyShell>
  );
};

const CompactScalarValue: React.FC<{
  value: unknown;
  isDarkTheme: boolean;
  singleLine?: boolean;
}> = ({ value, isDarkTheme, singleLine = false }) => {
  const colors = getViewerColors(isDarkTheme);
  const scalar = unwrapLosslessNumber(value);
  const scalarText =
    scalar === null ? 'null' : typeof scalar === 'string' ? scalar : String(scalar);
  const color =
    scalar === null
      ? colors.null
      : typeof scalar === 'boolean'
        ? colors.boolean
        : typeof scalar === 'number'
          ? colors.number
          : colors.string;

  return (
    <div
      style={{
        minWidth: 0,
        fontFamily: 'var(--vscode-editor-font-family, monospace)',
        fontSize: '13px',
        color,
        lineHeight: '1.5',
        whiteSpace: singleLine ? 'nowrap' : 'pre-wrap',
        overflow: singleLine ? 'hidden' : undefined,
        textOverflow: singleLine ? 'ellipsis' : undefined,
        wordBreak: singleLine ? undefined : 'break-word',
      }}
    >
      {scalarText}
    </div>
  );
};

function isInlineSimpleValue(
  value: unknown,
  siblingData: Record<string, unknown> | undefined,
  canRenderDocument: boolean,
): boolean {
  if (isLosslessNumberValue(value) || value === null || typeof value === 'number' || typeof value === 'boolean') {
    return true;
  }

  if (typeof value !== 'string') {
    return false;
  }

  if (canRenderDocument && detectDocument(value, siblingData)) {
    return false;
  }

  if (shouldCollapseLongText(value)) {
    return false;
  }

  return classifyStringContent(value).kind === 'plain';
}

const InlineValueRow: React.FC<{
  label: string;
  value: unknown;
  isDarkTheme: boolean;
  searchQuery?: string;
  currentMatchIndex?: number;
  matchIndexOffset?: number;
}> = ({ label, value, isDarkTheme, searchQuery, currentMatchIndex, matchIndexOffset = 0 }) => {
  const colors = getViewerColors(isDarkTheme);
  const isString = typeof value === 'string';
  const { element: highlighted } = isString
    ? highlightText(value, searchQuery, matchIndexOffset, currentMatchIndex ?? -1)
    : { element: null };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        padding: '8px 10px',
        borderRadius: '8px',
        border: `1px solid ${isDarkTheme ? 'rgba(110, 118, 129, 0.22)' : 'rgba(110, 118, 129, 0.14)'}`,
        backgroundColor: isDarkTheme ? 'rgba(110, 118, 129, 0.06)' : 'rgba(110, 118, 129, 0.03)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: '140px', maxWidth: '240px' }}>
        <span
          style={{
            color: colors.key,
            fontSize: '13px',
            fontWeight: 600,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {label}
        </span>
        <TypeBadge label={getScalarTypeLabel(value)} isDarkTheme={isDarkTheme} />
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        {isString ? (
          <div
            style={{
              fontFamily: 'var(--vscode-editor-font-family, monospace)',
              fontSize: '13px',
              lineHeight: '1.5',
              color: colors.string,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {highlighted}
          </div>
        ) : (
          <CompactScalarValue value={value} isDarkTheme={isDarkTheme} />
        )}
      </div>
    </div>
  );
};

const ArrayIndexLabel: React.FC<{ index: number; isDarkTheme: boolean }> = ({ index, isDarkTheme }) => (
  <span
    style={{
      display: 'inline-block',
      minWidth: '16px',
      fontFamily: 'var(--vscode-editor-font-family, monospace)',
      fontSize: '11px',
      lineHeight: 1,
      color: getViewerColors(isDarkTheme).mutedText,
      opacity: 0.72,
      textAlign: 'right',
    }}
  >
    {index}
  </span>
);

const ArrayItemBox: React.FC<{
  index: number;
  isDarkTheme: boolean;
  children: React.ReactNode;
}> = ({ index, isDarkTheme, children }) => (
  <div
    style={{
      border: `1px solid ${isDarkTheme ? 'rgba(110, 118, 129, 0.22)' : 'rgba(110, 118, 129, 0.14)'}`,
      borderRadius: '8px',
      backgroundColor: isDarkTheme ? 'rgba(110, 118, 129, 0.06)' : 'rgba(110, 118, 129, 0.03)',
      padding: '8px 10px',
    }}
  >
    <div style={{ marginBottom: '6px' }}>
      <ArrayIndexLabel index={index} isDarkTheme={isDarkTheme} />
    </div>
    {children}
  </div>
);

const InlineArrayItemRow: React.FC<{
  index: number;
  value: unknown;
  isDarkTheme: boolean;
  searchQuery?: string;
  currentMatchIndex?: number;
  matchIndexOffset?: number;
}> = ({ index, value, isDarkTheme, searchQuery, currentMatchIndex, matchIndexOffset = 0 }) => {
  const colors = getViewerColors(isDarkTheme);
  const isString = typeof value === 'string';
  const { element: highlighted } = isString
    ? highlightText(value, searchQuery, matchIndexOffset, currentMatchIndex ?? -1)
    : { element: null };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        padding: '8px 10px',
        borderRadius: '8px',
        border: `1px solid ${isDarkTheme ? 'rgba(110, 118, 129, 0.22)' : 'rgba(110, 118, 129, 0.14)'}`,
        backgroundColor: isDarkTheme ? 'rgba(110, 118, 129, 0.06)' : 'rgba(110, 118, 129, 0.03)',
      }}
    >
      <ArrayIndexLabel index={index} isDarkTheme={isDarkTheme} />
      <div style={{ minWidth: 0, flex: 1 }}>
        {isString ? (
          <div
            style={{
              fontFamily: 'var(--vscode-editor-font-family, monospace)',
              fontSize: '13px',
              lineHeight: '1.5',
              color: colors.string,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {highlighted}
          </div>
        ) : (
          <CompactScalarValue value={value} isDarkTheme={isDarkTheme} />
        )}
      </div>
    </div>
  );
};

function renderSyntaxHighlightedCode(
  code: string,
  language: string,
  colors: ReturnType<typeof getViewerColors>,
  searchQuery?: string,
  currentMatchIndex?: number,
  matchIndexOffset = 0,
): React.ReactNode {
  const tokens = tokenizeCode(code, language);
  let runningOffset = matchIndexOffset;

  return tokens.map((token, index) => {
    const start = runningOffset;
    const { element } = highlightText(token.text, searchQuery, start, currentMatchIndex ?? -1);
    runningOffset += countMatches(token.text, searchQuery || '');

    if (token.type === 'plain') {
      return <React.Fragment key={`code-token-${index}`}>{element}</React.Fragment>;
    }

    return (
      <span key={`code-token-${index}`} style={{ color: getCodeTokenColor(token.type, colors) }}>
        {element}
      </span>
    );
  });
}

function getCodeTokenColor(type: CodeTokenType, colors: ReturnType<typeof getViewerColors>): string {
  switch (type) {
    case 'comment':
      return colors.comment;
    case 'string':
      return colors.string;
    case 'number':
      return colors.number;
    case 'boolean':
      return colors.boolean;
    case 'keyword':
      return colors.keyword;
    case 'property':
      return colors.key;
    case 'tag':
      return colors.tag;
    case 'attribute':
      return colors.attribute;
    case 'variable':
      return colors.variable;
    default:
      return colors.bracket;
  }
}

function tokenizeCode(code: string, language: string): CodeToken[] {
  const normalized = language.trim().toLowerCase();
  const rules = getTokenRules(normalized);
  const tokens: CodeToken[] = [];
  let remaining = code;

  while (remaining.length > 0) {
    let matched = false;

    for (const rule of rules) {
      const match = remaining.match(rule.regex);
      if (!match) {
        continue;
      }

      tokens.push({ type: rule.type, text: match[0] });
      remaining = remaining.slice(match[0].length);
      matched = true;
      break;
    }

    if (!matched) {
      tokens.push({ type: 'plain', text: remaining[0] });
      remaining = remaining.slice(1);
    }
  }

  return mergePlainTokens(tokens);
}

function mergePlainTokens(tokens: CodeToken[]): CodeToken[] {
  const merged: CodeToken[] = [];

  for (const token of tokens) {
    const previous = merged[merged.length - 1];
    if (previous && previous.type === token.type && token.type === 'plain') {
      previous.text += token.text;
      continue;
    }
    merged.push({ ...token });
  }

  return merged;
}

function getTokenRules(language: string): Array<{ type: CodeTokenType; regex: RegExp }> {
  if (language === 'json') {
    return [
      { type: 'property', regex: /^"(?:\\.|[^"\\])*"(?=\s*:)/ },
      { type: 'string', regex: /^"(?:\\.|[^"\\])*"/ },
      { type: 'boolean', regex: /^(?:true|false|null)\b/ },
      { type: 'number', regex: /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/ },
    ];
  }

  if (language === 'xml' || language === 'html') {
    return [
      { type: 'comment', regex: /^<!--[\s\S]*?-->/ },
      { type: 'tag', regex: /^<\/?[A-Za-z_][\w:.-]*/ },
      { type: 'attribute', regex: /^[A-Za-z_][\w:.-]*(?==)/ },
      { type: 'string', regex: /^"(?:\\.|[^"\\])*"|^'(?:\\.|[^'\\])*'/ },
      { type: 'number', regex: /^-?(?:0|[1-9]\d*)(?:\.\d+)?/ },
    ];
  }

  const commonRules: Array<{ type: CodeTokenType; regex: RegExp }> = [
    { type: 'comment', regex: /^\/\/[^\n]*/ },
    { type: 'comment', regex: /^\/\*[\s\S]*?\*\// },
    { type: 'comment', regex: /^#[^\n]*/ },
    { type: 'comment', regex: /^--[^\n]*/ },
    { type: 'string', regex: /^"""[\s\S]*?"""|^'''[\s\S]*?'''|^`(?:\\.|[^`])*`|^"(?:\\.|[^"\\])*"|^'(?:\\.|[^'\\])*'/ },
    { type: 'number', regex: /^-?(?:0|[1-9]\d*)(?:\.\d+)?/ },
    { type: 'boolean', regex: /^(?:true|false|null|undefined|None)\b/ },
  ];

  if (language === 'python') {
    return [
      ...commonRules,
      { type: 'keyword', regex: /^(?:def|class|return|if|elif|else|for|while|try|except|finally|import|from|as|with|lambda|pass|yield|raise|async|await|match|case|in|is|and|or|not)\b/ },
      { type: 'variable', regex: /^(?:self|cls)\b/ },
    ];
  }

  if (language === 'sql') {
    return [
      { type: 'comment', regex: /^--[^\n]*/ },
      { type: 'comment', regex: /^\/\*[\s\S]*?\*\// },
      { type: 'string', regex: /^'(?:''|[^'])*'/ },
      { type: 'number', regex: /^-?(?:0|[1-9]\d*)(?:\.\d+)?/ },
      { type: 'keyword', regex: /^(?:SELECT|FROM|WHERE|GROUP|BY|ORDER|LIMIT|JOIN|LEFT|RIGHT|INNER|OUTER|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|AS|AND|OR|ON|HAVING|CASE|WHEN|THEN|ELSE|END|DISTINCT|UNION)\b/i },
    ];
  }

  if (language === 'bash' || language === 'shell' || language === 'sh') {
    return [
      { type: 'comment', regex: /^#[^\n]*/ },
      { type: 'string', regex: /^"(?:\\.|[^"\\])*"|^'(?:\\.|[^'\\])*'/ },
      { type: 'variable', regex: /^\$\{[^}]+\}|^\$[A-Za-z_][\w]*/ },
      { type: 'keyword', regex: /^(?:if|then|else|fi|for|do|done|case|esac|function|export|local|readonly|echo|cd|grep|cat|uv|python|python3)\b/ },
      { type: 'number', regex: /^-?(?:0|[1-9]\d*)(?:\.\d+)?/ },
    ];
  }

  return [
    ...commonRules,
    { type: 'keyword', regex: /^(?:const|let|var|function|return|if|else|for|while|class|import|from|export|default|type|interface|extends|implements|async|await|new|switch|case|break|continue|try|catch|throw|public|private|protected|package|func|struct|map|enum|typeof|instanceof)\b/ },
    { type: 'variable', regex: /^(?:this|super)\b/ },
  ];
}

const CodeBlock: React.FC<{
  code: string;
  language: string;
  isDarkTheme: boolean;
  searchQuery?: string;
  currentMatchIndex?: number;
  matchIndexOffset?: number;
}> = ({ code, language, isDarkTheme, searchQuery, currentMatchIndex, matchIndexOffset = 0 }) => {
  const colors = getViewerColors(isDarkTheme);
  const highlighted = renderSyntaxHighlightedCode(
    code,
    language,
    colors,
    searchQuery,
    currentMatchIndex,
    matchIndexOffset,
  );
  const prismTheme = isDarkTheme ? oneDark : oneLight;
  const syntaxTheme = {
    ...prismTheme,
    'pre[class*="language-"]': {
      ...(prismTheme['pre[class*="language-"]'] || {}),
      background: 'transparent',
      margin: 0,
      padding: 0,
      textShadow: 'none',
    },
    'code[class*="language-"]': {
      ...(prismTheme['code[class*="language-"]'] || {}),
      background: 'transparent',
      fontFamily: 'var(--vscode-editor-font-family, monospace)',
      fontSize: '12px',
      lineHeight: '1.6',
      textShadow: 'none',
    },
  };

  return (
    <div>
      <div style={{ marginBottom: '8px' }}>
        <TypeBadge label={`code · ${language}`} isDarkTheme={isDarkTheme} />
      </div>
      {searchQuery ? (
        <pre
          style={{
            margin: 0,
            padding: '12px',
            borderRadius: '8px',
            backgroundColor: colors.nestedBackground,
            border: `1px solid ${colors.inputBorder}`,
            overflowX: 'auto',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            fontFamily: 'var(--vscode-editor-font-family, monospace)',
            fontSize: '12px',
            lineHeight: '1.5',
            color: colors.string,
          }}
        >
          {highlighted}
        </pre>
      ) : (
        <SyntaxHighlighter
          language={language}
          style={syntaxTheme}
          customStyle={{
            margin: 0,
            padding: '12px',
            borderRadius: '8px',
            background: colors.nestedBackground,
            border: `1px solid ${colors.inputBorder}`,
            fontFamily: 'var(--vscode-editor-font-family, monospace)',
            fontSize: '12px',
            lineHeight: '1.5',
          }}
          codeTagProps={{ style: { background: 'transparent' } }}
          wrapLongLines
        >
          {code}
        </SyntaxHighlighter>
      )}
    </div>
  );
};

type MarkdownBlock =
  | { kind: 'heading'; depth: number; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: string[] }
  | { kind: 'blockquote'; lines: string[] }
  | { kind: 'code'; language: string; code: string };

function parseMarkdownBlocks(markdown: string): MarkdownBlock[] {
  const lines = markdown.split('\n');
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith('```')) {
      const language = trimmed.slice(3).trim() || 'text';
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push({ kind: 'code', language, code: codeLines.join('\n') });
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      blocks.push({ kind: 'heading', depth: headingMatch[1].length, text: headingMatch[2] });
      index += 1;
      continue;
    }

    if (/^[-*+]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*+]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*+]\s+/, ''));
        index += 1;
      }
      blocks.push({ kind: 'ul', items });
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s+/, ''));
        index += 1;
      }
      blocks.push({ kind: 'ol', items });
      continue;
    }

    if (trimmed.startsWith('>')) {
      const quoteLines: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith('>')) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ''));
        index += 1;
      }
      blocks.push({ kind: 'blockquote', lines: quoteLines });
      continue;
    }

    const paragraphLines: string[] = [];
    while (index < lines.length) {
      const next = lines[index];
      const nextTrimmed = next.trim();
      if (
        !nextTrimmed ||
        nextTrimmed.startsWith('```') ||
        /^#{1,6}\s+/.test(next) ||
        /^[-*+]\s+/.test(nextTrimmed) ||
        /^\d+\.\s+/.test(nextTrimmed) ||
        nextTrimmed.startsWith('>')
      ) {
        break;
      }
      paragraphLines.push(nextTrimmed);
      index += 1;
    }
    blocks.push({ kind: 'paragraph', text: paragraphLines.join(' ') });
  }

  return blocks;
}

const InlineMarkdownText: React.FC<{
  text: string;
  isDarkTheme: boolean;
  searchQuery?: string;
  currentMatchIndex?: number;
  matchIndexOffset?: number;
}> = ({ text, isDarkTheme, searchQuery, currentMatchIndex, matchIndexOffset = 0 }) => {
  const colors = getViewerColors(isDarkTheme);
  const segments = text.split(/(`[^`\n]+`)/g);
  let runningOffset = matchIndexOffset;

  return (
    <>
      {segments.map((segment, index) => {
        if (segment.startsWith('`') && segment.endsWith('`')) {
          return (
            <code
              key={`inline-code-${index}`}
              style={{
                fontFamily: 'var(--vscode-editor-font-family, monospace)',
                backgroundColor: colors.nestedBackground,
                border: `1px solid ${colors.inputBorder}`,
                borderRadius: '4px',
                padding: '1px 4px',
                fontSize: '12px',
              }}
            >
              {segment.slice(1, -1)}
            </code>
          );
        }

        const start = runningOffset;
        const { element } = highlightText(segment, searchQuery, start, currentMatchIndex ?? -1);
        runningOffset += countMatches(segment, searchQuery || '');
        return <React.Fragment key={`inline-text-${index}`}>{element}</React.Fragment>;
      })}
    </>
  );
};

const MarkdownRenderer: React.FC<{
  markdown: string;
  isDarkTheme: boolean;
  searchQuery?: string;
  currentMatchIndex?: number;
  matchIndexOffset?: number;
}> = ({ markdown, isDarkTheme, searchQuery, currentMatchIndex, matchIndexOffset = 0 }) => {
  const colors = getViewerColors(isDarkTheme);
  const blocks = parseMarkdownBlocks(markdown);
  let runningOffset = matchIndexOffset;

  const consumeOffset = (text: string) => {
    const current = runningOffset;
    runningOffset += countMatches(text, searchQuery || '');
    return current;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {blocks.map((block, index) => {
        if (block.kind === 'heading') {
          const start = consumeOffset(block.text);
          const fontSize = Math.max(16, 24 - block.depth * 2);
          return (
            <div
              key={`md-heading-${index}`}
              style={{
                fontSize: `${fontSize}px`,
                fontWeight: 700,
                lineHeight: '1.3',
                color: colors.badgeText,
                fontFamily: 'var(--vscode-font-family, sans-serif)',
              }}
            >
              <InlineMarkdownText
                text={block.text}
                isDarkTheme={isDarkTheme}
                searchQuery={searchQuery}
                currentMatchIndex={currentMatchIndex}
                matchIndexOffset={start}
              />
            </div>
          );
        }

        if (block.kind === 'paragraph') {
          const start = consumeOffset(block.text);
          return (
            <div
              key={`md-paragraph-${index}`}
              style={{
                color: colors.badgeText,
                lineHeight: '1.6',
                fontSize: '13px',
                fontFamily: 'var(--vscode-font-family, sans-serif)',
              }}
            >
              <InlineMarkdownText
                text={block.text}
                isDarkTheme={isDarkTheme}
                searchQuery={searchQuery}
                currentMatchIndex={currentMatchIndex}
                matchIndexOffset={start}
              />
            </div>
          );
        }

        if (block.kind === 'ul' || block.kind === 'ol') {
          const items = block.items;
          return (
            <div
              key={`md-list-${index}`}
              style={{
                display: 'grid',
                gap: '6px',
                fontFamily: 'var(--vscode-font-family, sans-serif)',
                fontSize: '13px',
              }}
            >
              {items.map((item, itemIndex) => {
                const start = consumeOffset(item);
                return (
                  <div key={`md-list-item-${itemIndex}`} style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                    <span style={{ color: colors.mutedText, minWidth: '18px', textAlign: 'right' }}>
                      {block.kind === 'ol' ? `${itemIndex + 1}.` : '•'}
                    </span>
                    <div style={{ color: colors.badgeText, lineHeight: '1.5' }}>
                      <InlineMarkdownText
                        text={item}
                        isDarkTheme={isDarkTheme}
                        searchQuery={searchQuery}
                        currentMatchIndex={currentMatchIndex}
                        matchIndexOffset={start}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          );
        }

        if (block.kind === 'blockquote') {
          const text = block.lines.join(' ');
          const start = consumeOffset(text);
          return (
            <div
              key={`md-quote-${index}`}
              style={{
                padding: '8px 12px',
                borderLeft: `3px solid ${colors.quoteBorder}`,
                backgroundColor: colors.nestedBackground,
                color: colors.mutedText,
                fontStyle: 'italic',
                lineHeight: '1.6',
                fontFamily: 'var(--vscode-font-family, sans-serif)',
              }}
            >
              <InlineMarkdownText
                text={text}
                isDarkTheme={isDarkTheme}
                searchQuery={searchQuery}
                currentMatchIndex={currentMatchIndex}
                matchIndexOffset={start}
              />
            </div>
          );
        }

        return (
          <CodeBlock
            key={`md-code-${index}`}
            code={block.code}
            language={block.language}
            isDarkTheme={isDarkTheme}
            searchQuery={searchQuery}
            currentMatchIndex={currentMatchIndex}
            matchIndexOffset={consumeOffset(block.code)}
          />
        );
      })}
    </div>
  );
};

const PrettyStringNode: React.FC<BaseNodeProps> = ({
  keyName,
  value,
  isDarkTheme,
  depth,
  siblingData,
  onOpenDocument,
  searchQuery,
  currentMatchIndex,
  matchIndexOffset = 0,
}) => {
  const colors = getViewerColors(isDarkTheme);
  const [showRawString, setShowRawString] = useState(false);
  const [isExpanded, setIsExpanded] = useState(!shouldCollapseLongText(value));
  const detectedDoc = onOpenDocument ? detectDocument(value, siblingData) : null;
  const doc = detectedDoc && !showRawString ? detectedDoc : null;
  const classification = classifyStringContent(value);
  const rawToggleAction =
    detectedDoc || classification.kind === 'json' || classification.kind === 'markdown' || classification.kind === 'xml'
      ? (
          <ActionIconButton
            title={showRawString ? 'Show rendered' : 'Show raw'}
            icon={
              <span
                style={{
                  fontFamily: 'var(--vscode-editor-font-family, monospace)',
                  fontSize: '10px',
                  lineHeight: 1,
                }}
              >
                {'{}'}
              </span>
            }
            isDarkTheme={isDarkTheme}
            active={showRawString}
            onClick={() => setShowRawString((current) => !current)}
          />
        )
      : undefined;
  const canCollapseVisibleText = shouldCollapseLongText(value) && (showRawString || classification.kind === 'plain');
  const collapseAction = canCollapseVisibleText ? (
    <ActionIconButton
      title={isExpanded ? 'Collapse' : 'Expand'}
      icon={isExpanded ? 'codicon-chevron-down' : 'codicon-chevron-right'}
      isDarkTheme={isDarkTheme}
      onClick={() => setIsExpanded((current) => !current)}
    />
  ) : undefined;
  const plainStringActions = rawToggleAction && collapseAction ? (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
      {rawToggleAction}
      {collapseAction}
    </div>
  ) : rawToggleAction || collapseAction;

  if (doc) {
    return (
      <PrettyShell
        label={keyName}
        badge={doc.type}
        isDarkTheme={isDarkTheme}
        depth={depth}
        actions={rawToggleAction}
        compact
      >
        <DocumentButton doc={doc} isDarkTheme={isDarkTheme} onOpenDocument={onOpenDocument} />
      </PrettyShell>
    );
  }

  if (classification.kind === 'json' && depth < MAX_PRETTY_DEPTH && !showRawString) {
    return (
      <PrettyShell
        label={keyName}
        badge={classification.label}
        isDarkTheme={isDarkTheme}
        depth={depth}
        actions={rawToggleAction}
      >
        <PrettyJSONNode
          keyName={null}
          value={classification.parsed}
          isDarkTheme={isDarkTheme}
          depth={depth + 1}
          path={[]}
          onOpenDocument={onOpenDocument}
          searchQuery={searchQuery}
          currentMatchIndex={currentMatchIndex}
          matchIndexOffset={matchIndexOffset}
        />
      </PrettyShell>
    );
  }

  if (classification.kind === 'markdown' && !showRawString) {
    return (
      <PrettyShell
        label={keyName}
        badge="markdown"
        isDarkTheme={isDarkTheme}
        depth={depth}
        actions={rawToggleAction}
      >
        <MarkdownRenderer
          markdown={value}
          isDarkTheme={isDarkTheme}
          searchQuery={searchQuery}
          currentMatchIndex={currentMatchIndex}
          matchIndexOffset={matchIndexOffset}
        />
      </PrettyShell>
    );
  }

  if (classification.kind === 'xml' && !showRawString) {
    return (
      <PrettyShell
        label={keyName}
        badge="xml"
        isDarkTheme={isDarkTheme}
        depth={depth}
        actions={rawToggleAction}
      >
        <CodeBlock
          code={value}
          language="xml"
          isDarkTheme={isDarkTheme}
          searchQuery={searchQuery}
          currentMatchIndex={currentMatchIndex}
          matchIndexOffset={matchIndexOffset}
        />
      </PrettyShell>
    );
  }

  if (classification.kind === 'code') {
    const code = classification.fenced ? unwrapFencedCode(value)?.code || value : value;
    return (
      <PrettyShell
        label={keyName}
        badge={classification.fenced ? 'fenced code' : 'code'}
        isDarkTheme={isDarkTheme}
        depth={depth}
      >
        <CodeBlock
          code={code}
          language={classification.language}
          isDarkTheme={isDarkTheme}
          searchQuery={searchQuery}
          currentMatchIndex={currentMatchIndex}
          matchIndexOffset={matchIndexOffset}
        />
      </PrettyShell>
    );
  }

  const previewText = isExpanded ? value : getStringPreview(value);
  const { element: highlighted } = highlightText(previewText, searchQuery, matchIndexOffset, currentMatchIndex ?? -1);
  return (
    <PrettyShell
      label={keyName}
      badge="string"
      isDarkTheme={isDarkTheme}
      depth={depth}
      actions={plainStringActions}
    >
      <pre
        style={{
          margin: 0,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          fontFamily: 'var(--vscode-editor-font-family, monospace)',
          fontSize: '13px',
          lineHeight: '1.5',
          color: colors.string,
        }}
      >
        {highlighted}
      </pre>
    </PrettyShell>
  );
};

const PrettyArrayNode: React.FC<BaseNodeProps> = ({
  keyName,
  value,
  isDarkTheme,
  depth,
  onOpenDocument,
  searchQuery,
  currentMatchIndex,
  matchIndexOffset = 0,
}) => {
  const colors = getViewerColors(isDarkTheme);
  const [isExpanded, setIsExpanded] = useState(true);
  const arrayValue = value as unknown[];
  const columns = getUniformObjectArrayColumns(arrayValue);

  const content = !isExpanded ? (
    <div
      style={{
        color: colors.mutedText,
        fontFamily: 'var(--vscode-font-family, sans-serif)',
        fontSize: '13px',
      }}
    >
      {`${arrayValue.length} items`}
    </div>
  ) : columns ? (
    <div style={{ overflowX: 'auto' }}>
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontFamily: 'var(--vscode-font-family, sans-serif)',
          fontSize: '13px',
        }}
      >
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column}
                style={{
                  textAlign: 'left',
                  padding: '8px',
                  borderBottom: `1px solid ${colors.inputBorder}`,
                  color: colors.key,
                  fontWeight: 600,
                }}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {arrayValue.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`} style={{ backgroundColor: rowIndex % 2 === 0 ? 'transparent' : colors.tableStripe }}>
              {columns.map((column) => {
                const cellValue = unwrapLosslessNumber((row as Record<string, unknown>)[column]);
                return (
                  <td
                    key={`${rowIndex}-${column}`}
                    style={{
                      padding: '8px',
                      borderBottom: `1px solid ${colors.inputBorder}`,
                      color: typeof cellValue === 'string' ? colors.string : colors.badgeText,
                      verticalAlign: 'top',
                    }}
                  >
                    {typeof cellValue === 'string' ? getStringPreview(cellValue, 90) : String(cellValue)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <div style={{ display: 'grid', gap: '10px' }}>
      {arrayValue.map((item, index) => (
        isInlineSimpleValue(item, isRecord(item) ? item : undefined, Boolean(onOpenDocument)) ? (
          <InlineArrayItemRow
            key={`array-${index}`}
            index={index}
            value={item}
            isDarkTheme={isDarkTheme}
            searchQuery={searchQuery}
            currentMatchIndex={currentMatchIndex}
            matchIndexOffset={matchIndexOffset}
          />
        ) : (
          <ArrayItemBox key={`array-${index}`} index={index} isDarkTheme={isDarkTheme}>
            <PrettyJSONNode
              keyName={null}
              value={item}
              isDarkTheme={isDarkTheme}
              depth={depth + 1}
              path={[]}
              siblingData={isRecord(item) ? item : undefined}
              onOpenDocument={onOpenDocument}
              searchQuery={searchQuery}
              currentMatchIndex={currentMatchIndex}
              matchIndexOffset={matchIndexOffset}
            />
          </ArrayItemBox>
        )
      ))}
    </div>
  );

  return (
    <PrettyShell
      label={keyName}
      badge={`list · ${arrayValue.length}`}
      isDarkTheme={isDarkTheme}
      depth={depth}
      actions={<ActionIconButton title={isExpanded ? 'Collapse' : 'Expand'} icon={isExpanded ? 'codicon-chevron-down' : 'codicon-chevron-right'} isDarkTheme={isDarkTheme} onClick={() => setIsExpanded((current) => !current)} />}
    >
      {content}
    </PrettyShell>
  );
};

const PrettyObjectNode: React.FC<BaseNodeProps> = ({
  keyName,
  value,
  isDarkTheme,
  depth,
  onOpenDocument,
  searchQuery,
  currentMatchIndex,
  matchIndexOffset = 0,
}) => {
  const entries = Object.entries(value as Record<string, unknown>);

  const objectContent = (
    <div style={{ display: 'grid', gap: '10px' }}>
      {entries.map(([childKey, childValue]) => (
        isInlineSimpleValue(childValue, value as Record<string, unknown>, Boolean(onOpenDocument)) ? (
          <InlineValueRow
            key={childKey}
            label={childKey}
            value={childValue}
            isDarkTheme={isDarkTheme}
            searchQuery={searchQuery}
            currentMatchIndex={currentMatchIndex}
            matchIndexOffset={matchIndexOffset}
          />
        ) : (
          <PrettyJSONNode
            key={childKey}
            keyName={childKey}
            value={childValue}
            isDarkTheme={isDarkTheme}
            depth={depth + 1}
            path={[]}
            siblingData={value as Record<string, unknown>}
            onOpenDocument={onOpenDocument}
            searchQuery={searchQuery}
            currentMatchIndex={currentMatchIndex}
            matchIndexOffset={matchIndexOffset}
          />
        )
      ))}
    </div>
  );

  if (keyName === null) {
    return objectContent;
  }

  return (
    <PrettyShell label={keyName} badge={`object · ${entries.length}`} isDarkTheme={isDarkTheme} depth={depth}>
      {objectContent}
    </PrettyShell>
  );
};

const PrettyJSONNode: React.FC<BaseNodeProps> = ({
  keyName,
  value,
  isDarkTheme,
  depth,
  siblingData,
  onOpenDocument,
  searchQuery,
  currentMatchIndex,
  matchIndexOffset = 0,
}) => {
  if (depth > MAX_PRETTY_DEPTH) {
    return (
      <PrettyShell label={keyName} badge="nested" isDarkTheme={isDarkTheme} depth={depth} compact>
        <div
          style={{
            fontFamily: 'var(--vscode-editor-font-family, monospace)',
            fontSize: '12px',
            color: getViewerColors(isDarkTheme).mutedText,
          }}
        >
          More nested content is hidden here. Switch to raw mode to inspect it.
        </div>
      </PrettyShell>
    );
  }

  if (isLosslessNumberValue(value) || value === null || typeof value === 'number' || typeof value === 'boolean') {
    return <ScalarBox label={keyName} value={value} isDarkTheme={isDarkTheme} depth={depth} />;
  }

  if (typeof value === 'string') {
    return (
      <PrettyStringNode
        keyName={keyName}
        value={value}
        isDarkTheme={isDarkTheme}
        depth={depth}
        path={[]}
        siblingData={siblingData}
        onOpenDocument={onOpenDocument}
        searchQuery={searchQuery}
        currentMatchIndex={currentMatchIndex}
        matchIndexOffset={matchIndexOffset}
      />
    );
  }

  if (Array.isArray(value)) {
    return (
      <PrettyArrayNode
        keyName={keyName}
        value={value}
        isDarkTheme={isDarkTheme}
        depth={depth}
        path={[]}
        onOpenDocument={onOpenDocument}
        searchQuery={searchQuery}
        currentMatchIndex={currentMatchIndex}
        matchIndexOffset={matchIndexOffset}
      />
    );
  }

  if (isRecord(value)) {
    return (
      <PrettyObjectNode
        keyName={keyName}
        value={value}
        isDarkTheme={isDarkTheme}
        depth={depth}
        path={[]}
        siblingData={siblingData}
        onOpenDocument={onOpenDocument}
        searchQuery={searchQuery}
        currentMatchIndex={currentMatchIndex}
        matchIndexOffset={matchIndexOffset}
      />
    );
  }

  return <ScalarBox label={keyName} value={String(value)} isDarkTheme={isDarkTheme} depth={depth} />;
};

const RawJSONNode: React.FC<BaseNodeProps> = ({
  keyName,
  value,
  isDarkTheme,
  depth,
  path,
  onChange,
  siblingData,
  onOpenDocument,
  searchQuery,
  currentMatchIndex,
  matchIndexOffset = 0,
}) => {
  const [isExpanded, setIsExpanded] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  const [originalType] = useState<string>(typeof value);
  const [showRawDocument, setShowRawDocument] = useState(false);
  const colors = getViewerColors(isDarkTheme);

  const indent = depth * 15;

  const isExpandable = (val: any) => {
    if (isLosslessNumberValue(val)) {
      return false;
    }

    return (
      val !== null &&
      typeof val === 'object' &&
      (Array.isArray(val) ? val.length > 0 : Object.keys(val).length > 0)
    );
  };

  const getValuePreview = (val: any): string => {
    if (Array.isArray(val)) {
      return val.length === 0 ? '[]' : `[${val.length} items]`;
    }
    if (val !== null && typeof val === 'object') {
      const keys = Object.keys(val);
      return keys.length === 0 ? '{}' : `{${keys.length} keys}`;
    }
    return '';
  };

  const parseEditValue = (nextEditValue: string): any => {
    const trimmed = nextEditValue.trim();

    if (originalType === 'string') {
      return nextEditValue;
    }

    if (trimmed === 'null') {
      return null;
    }

    if (trimmed === 'true') {
      return true;
    }

    if (trimmed === 'false') {
      return false;
    }

    if (!Number.isNaN(Number(trimmed)) && trimmed !== '') {
      return Number(trimmed);
    }

    return nextEditValue;
  };

  const saveEdit = () => {
    if (!onChange) {
      return;
    }
    onChange(path, parseEditValue(editValue));
    setIsEditing(false);
  };

  const handleChange = (nextEditValue: string) => {
    setEditValue(nextEditValue);
    if (!isEditing) {
      setIsEditing(true);
    }

    if (onChange) {
      onChange(path, parseEditValue(nextEditValue));
    }
  };

  const cancelEdit = () => {
    setIsEditing(false);
    setEditValue('');
  };

  const getTextareaStyle = (color: string) => ({
    fontFamily: 'var(--vscode-editor-font-family, monospace)',
    fontSize: 'var(--vscode-editor-font-size, 13px)',
    padding: '2px 4px',
    border: `1px solid ${colors.inputBorder}`,
    borderRadius: '2px',
    backgroundColor: colors.inputBackground,
    color,
    outline: 'none',
    width: '100%',
    resize: 'both' as const,
    lineHeight: '1.4',
    overflow: 'auto',
    cursor: onChange ? 'text' : 'default',
    boxSizing: 'border-box' as const,
  });

  const getRows = (content: string) => {
    if (content.length < 100) {
      return 1;
    }
    if (content.length < 500) {
      return 5;
    }
    if (content.length < 2000) {
      return 15;
    }
    return 30;
  };

  const renderValue = (val: any) => {
    const editable = onChange !== undefined;

    if (typeof val === 'string' && !showRawDocument) {
      const doc = onOpenDocument ? detectDocument(val, siblingData) : null;
      if (doc) {
        return (
          <DocumentButton
            doc={doc}
            isDarkTheme={isDarkTheme}
            onOpenDocument={onOpenDocument}
            onShowRaw={() => setShowRawDocument(true)}
          />
        );
      }
    }

    if (isLosslessNumberValue(val)) {
      const numericValue = unwrapLosslessNumber(val);
      return (
        <textarea
          rows={getRows(String(numericValue))}
          value={isEditing ? editValue : String(numericValue)}
          onChange={(event) => handleChange(event.target.value)}
          onFocus={() => {
            if (!isEditing) {
              setEditValue(String(numericValue));
              setIsEditing(true);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              cancelEdit();
            } else if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              event.preventDefault();
              saveEdit();
            }
          }}
          readOnly={!editable}
          style={getTextareaStyle(colors.number)}
        />
      );
    }

    if (val === null) {
      return (
        <textarea
          rows={1}
          value={editValue || 'null'}
          onChange={(event) => handleChange(event.target.value)}
          onFocus={() => {
            if (!isEditing) {
              setEditValue('null');
              setIsEditing(true);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              cancelEdit();
            } else if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              event.preventDefault();
              saveEdit();
            }
          }}
          readOnly={!editable}
          style={getTextareaStyle(colors.null)}
        />
      );
    }

    if (typeof val === 'string') {
      const displayValue = isEditing ? editValue : val;
      if (searchQuery && !isEditing) {
        const { element: highlighted } = highlightText(val, searchQuery, matchIndexOffset, currentMatchIndex ?? -1);
        return (
          <pre
            style={{
              fontFamily: 'var(--vscode-editor-font-family, monospace)',
              fontSize: 'var(--vscode-editor-font-size, 13px)',
              padding: '2px 4px',
              border: `1px solid ${colors.inputBorder}`,
              borderRadius: '2px',
              backgroundColor: colors.inputBackground,
              color: colors.string,
              width: '100%',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              lineHeight: '1.4',
              margin: 0,
              cursor: editable ? 'text' : 'default',
              boxSizing: 'border-box',
              minHeight: '24px',
              maxHeight: '400px',
              overflow: 'auto',
            }}
            onClick={() => {
              if (editable) {
                setEditValue(val);
                setIsEditing(true);
              }
            }}
          >
            {highlighted}
          </pre>
        );
      }

      return (
        <textarea
          rows={getRows(displayValue)}
          value={displayValue}
          onChange={(event) => handleChange(event.target.value)}
          onFocus={() => {
            if (!isEditing) {
              setEditValue(val);
              setIsEditing(true);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              cancelEdit();
            } else if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              event.preventDefault();
              saveEdit();
            }
          }}
          readOnly={!editable}
          style={getTextareaStyle(colors.string)}
        />
      );
    }

    if (typeof val === 'number') {
      return (
        <textarea
          rows={1}
          value={isEditing ? editValue : String(val)}
          onChange={(event) => handleChange(event.target.value)}
          onFocus={() => {
            if (!isEditing) {
              setEditValue(String(val));
              setIsEditing(true);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              cancelEdit();
            } else if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              event.preventDefault();
              saveEdit();
            }
          }}
          readOnly={!editable}
          style={getTextareaStyle(colors.number)}
        />
      );
    }

    if (typeof val === 'boolean') {
      return (
        <textarea
          rows={1}
          value={isEditing ? editValue : String(val)}
          onChange={(event) => handleChange(event.target.value)}
          onFocus={() => {
            if (!isEditing) {
              setEditValue(String(val));
              setIsEditing(true);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              cancelEdit();
            } else if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              event.preventDefault();
              saveEdit();
            }
          }}
          readOnly={!editable}
          style={getTextareaStyle(colors.boolean)}
        />
      );
    }

    return null;
  };

  const toggleExpand = () => {
    if (isExpandable(value)) {
      setIsExpanded((current) => !current);
    }
  };

  if (!isExpandable(value)) {
    return (
      <div
        style={{
          paddingLeft: `${indent}px`,
          fontFamily: 'var(--vscode-editor-font-family, monospace)',
          fontSize: 'var(--vscode-editor-font-size, 13px)',
          lineHeight: '20px',
          marginBottom: '4px',
        }}
      >
        {keyName !== null && (
          <div style={{ marginBottom: '2px' }}>
            <span style={{ color: colors.key }}>"{keyLabelFromPath(keyName)}"</span>
            <span style={{ color: colors.bracket }}>:</span>
          </div>
        )}
        <div>{renderValue(value)}</div>
      </div>
    );
  }

  const isArray = Array.isArray(value);
  const entries = isArray ? value.map((entry: unknown, index: number) => [String(index), entry]) : Object.entries(value);

  return (
    <div>
      <div
        onClick={toggleExpand}
        style={{
          paddingLeft: `${indent}px`,
          fontFamily: 'var(--vscode-editor-font-family, monospace)',
          fontSize: 'var(--vscode-editor-font-size, 13px)',
          lineHeight: '20px',
          cursor: 'pointer',
          userSelect: 'none',
        }}
        onMouseEnter={(event) => {
          event.currentTarget.style.backgroundColor = colors.hoverBackground;
        }}
        onMouseLeave={(event) => {
          event.currentTarget.style.backgroundColor = 'transparent';
        }}
      >
        <i
          className={`codicon ${isExpanded ? 'codicon-chevron-down' : 'codicon-chevron-right'}`}
          style={{ marginRight: '4px', fontSize: '16px' }}
        />
        {keyName !== null && (
          <>
            <span style={{ color: colors.key }}>"{keyLabelFromPath(keyName)}"</span>
            <span style={{ color: colors.bracket }}>: </span>
          </>
        )}
        <span style={{ color: colors.bracket }}>
          {isArray ? '[' : '{'}
          {!isExpanded && (
            <>
              <span style={{ color: colors.bracket, opacity: 0.6 }}>{getValuePreview(value)}</span>
              {isArray ? ']' : '}'}
            </>
          )}
        </span>
      </div>

      {isExpanded && (
        <>
          {entries.map(([childKey, childValue], index) => (
            <RawJSONNode
              key={childKey}
              keyName={isArray ? null : childKey}
              value={childValue}
              isDarkTheme={isDarkTheme}
              depth={depth + 1}
              path={[...path, childKey]}
              onChange={onChange}
              siblingData={isArray ? undefined : value}
              onOpenDocument={onOpenDocument}
              searchQuery={searchQuery}
              currentMatchIndex={currentMatchIndex}
              matchIndexOffset={matchIndexOffset + index}
            />
          ))}
          <div
            style={{
              paddingLeft: `${indent}px`,
              fontFamily: 'var(--vscode-editor-font-family, monospace)',
              fontSize: 'var(--vscode-editor-font-size, 13px)',
              lineHeight: '20px',
            }}
          >
            <span style={{ color: colors.bracket }}>{isArray ? ']' : '}'}</span>
          </div>
        </>
      )}
    </div>
  );
};

export const JSONViewer: React.FC<JSONViewerProps> = ({
  data,
  isDarkTheme,
  depth = 0,
  onChange,
  onOpenDocument,
  searchQuery,
  currentMatchIndex,
  onMatchCountChange,
  defaultViewMode = 'pretty',
  hideViewToggle = false,
  containerPadding = '12px',
  containerBackgroundColor = 'var(--vscode-editor-background)',
}) => {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [viewMode, setViewMode] = React.useState<ViewMode>(defaultViewMode);

  const handleChange = (path: string[], newValue: any) => {
    if (!onChange) {
      return;
    }

    const newData = parse(stringify(data) || '{}') as any;
    let current: any = newData;

    for (let index = 0; index < path.length - 1; index += 1) {
      current = current[path[index]];
    }

    current[path[path.length - 1]] = newValue;
    onChange(newData);
  };

  React.useEffect(() => {
    if (!containerRef.current || !searchQuery) {
      onMatchCountChange?.(0);
      return;
    }

    setTimeout(() => {
      const matches = containerRef.current?.querySelectorAll('[data-match-index]') || [];
      onMatchCountChange?.(matches.length);

      if (currentMatchIndex !== undefined && currentMatchIndex >= 0 && currentMatchIndex < matches.length) {
        const currentMatch = matches[currentMatchIndex];
        currentMatch?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        matches.forEach((match, index) => {
          (match as HTMLElement).style.backgroundColor = index === currentMatchIndex ? '#f0a020' : '#ffff00';
        });
      }
    }, 0);
  }, [searchQuery, currentMatchIndex, data, onMatchCountChange, viewMode]);

  const renderPrettyRoot = () => (
    <PrettyJSONNode
      keyName={null}
      value={data}
      isDarkTheme={isDarkTheme}
      depth={depth}
      path={[]}
      siblingData={isRecord(data) ? data : undefined}
      onOpenDocument={onOpenDocument}
      searchQuery={searchQuery}
      currentMatchIndex={currentMatchIndex}
      matchIndexOffset={0}
    />
  );

  const renderRawRoot = () => {
    const isObject = data !== null && typeof data === 'object' && !Array.isArray(data);
    const isArray = Array.isArray(data);

    if (isObject || isArray) {
      return (
        <>
          {Object.entries(data).map(([key, value]) => (
            <RawJSONNode
              key={key}
              keyName={isArray ? null : key}
              value={value}
              isDarkTheme={isDarkTheme}
              depth={0}
              path={[key]}
              onChange={onChange ? handleChange : undefined}
              siblingData={isArray ? undefined : data}
              onOpenDocument={onOpenDocument}
              searchQuery={searchQuery}
              currentMatchIndex={currentMatchIndex}
              matchIndexOffset={0}
            />
          ))}
        </>
      );
    }

    return (
      <RawJSONNode
        keyName={null}
        value={data}
        isDarkTheme={isDarkTheme}
        depth={depth}
        path={[]}
        onChange={onChange ? handleChange : undefined}
        onOpenDocument={onOpenDocument}
        searchQuery={searchQuery}
        currentMatchIndex={currentMatchIndex}
        matchIndexOffset={0}
      />
    );
  };

  return (
    <div
      ref={containerRef}
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'auto',
        padding: containerPadding,
        backgroundColor: containerBackgroundColor,
      }}
    >
      {!hideViewToggle && (
        <ViewerToggle
          viewMode={viewMode}
          onChange={setViewMode}
          isDarkTheme={isDarkTheme}
          editable={onChange !== undefined}
        />
      )}
      {viewMode === 'pretty' ? renderPrettyRoot() : renderRawRoot()}
    </div>
  );
};
