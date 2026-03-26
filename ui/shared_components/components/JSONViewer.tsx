import React, { useState } from 'react';
import { parse, stringify } from 'lossless-json';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { detectDocument, formatFileSize, getDocumentKey, DetectedDocument } from '../utils/documentDetection';
import {
  applyDocumentReplacement,
  inferDocumentTypeFromMimeOrName,
  pickReplacementDocumentFromBrowser,
  type ReplacementDocumentFile,
} from '../utils/documentReplacement';
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
import {
  detectFlattenedMessageGroups,
  detectMessageLikeArray,
  detectMessageLikeObject,
  type FlattenedMessageGroup,
  type MessageMetadataEntry,
  type MessageRoleStyle,
} from '../utils/messageLike';
import { useDocumentContext } from '../contexts/DocumentContext';
import { PrismStyleMap, withTransparentPrismTheme } from '../utils/prismTheme';

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
  viewMode?: ViewMode;
  onViewModeChange?: (next: ViewMode) => void;
  hideViewToggle?: boolean;
  containerPadding?: string | number;
  containerBackgroundColor?: string;
  scrollMode?: 'internal' | 'external';
}

declare global {
  interface Window {
    vscode?: {
      postMessage: (message: unknown) => void;
    };
  }
}

interface BaseNodeProps {
  keyName: string | null;
  value: any;
  isDarkTheme: boolean;
  depth: number;
  path: string[];
  siblingData?: Record<string, unknown>;
  onChange?: (path: string[], newValue: any) => void;
  onReplaceDocument?: (path: string[], doc: DetectedDocument) => void;
  onJumpToRaw?: (path: string[]) => void;
  onOpenDocument?: (doc: DetectedDocument) => void;
  focusRequest?: FocusRequest | null;
  onFocusHandled?: (nonce: number) => void;
  searchQuery?: string;
  currentMatchIndex?: number;
  matchIndexOffset?: number;
}

export type ViewMode = 'pretty' | 'raw';
type FocusRequest = { path: string[]; nonce: number; cursorOffset: number | null; selectedText: string | null };
type SelectionSnapshot = { cursorOffset: number | null; selectedText: string | null };
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

function pathsEqual(left: string[], right: string[] | null | undefined): boolean {
  if (!right || left.length !== right.length) {
    return false;
  }

  return left.every((segment, index) => segment === right[index]);
}

function isProperPathPrefix(prefix: string[], fullPath: string[] | null | undefined): boolean {
  if (!fullPath || prefix.length >= fullPath.length) {
    return false;
  }

  return prefix.every((segment, index) => segment === fullPath[index]);
}

function getSelectionLeafOffset(): number | null {
  if (typeof window === 'undefined') {
    return null;
  }

  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) {
    return null;
  }

  return Math.max(0, selection.getRangeAt(0).startOffset);
}

function getSelectionLeafText(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }

  const selection = window.getSelection();
  if (!selection) {
    return null;
  }

  const text = selection.toString().trim();
  if (!text) {
    return null;
  }

  return text.length <= 120 ? text : text.slice(0, 120);
}

function getTransientSelectionRange(text: string, cursorOffset: number | null, selectedText: string | null): { start: number; end: number; caret: number } {
  const caret = Math.max(0, Math.min(cursorOffset ?? 0, text.length));
  if (text.length === 0) {
    return { start: caret, end: caret, caret };
  }

  const needle = selectedText?.trim();
  if (!needle) {
    return { start: caret, end: caret, caret };
  }

  let bestStart = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  let searchIndex = 0;
  while (searchIndex <= text.length) {
    const matchIndex = text.indexOf(needle, searchIndex);
    if (matchIndex === -1) {
      break;
    }

    const distance = Math.abs(matchIndex - caret);
    if (distance < bestDistance) {
      bestStart = matchIndex;
      bestDistance = distance;
    }
    searchIndex = matchIndex + 1;
  }

  if (bestStart === -1) {
    return { start: caret, end: caret, caret };
  }

  return { start: bestStart, end: bestStart + needle.length, caret: bestStart };
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
    onClick={(event) => {
      event.stopPropagation();
      onClick();
    }}
    onDoubleClick={(event) => {
      event.stopPropagation();
    }}
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

const HoverActionSlot: React.FC<{
  visible: boolean;
  children: React.ReactNode;
}> = ({ visible, children }) => (
  <div
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      opacity: visible ? 1 : 0,
      pointerEvents: visible ? 'auto' : 'none',
      transition: 'opacity 120ms ease',
    }}
  >
    {children}
  </div>
);

const FramedContentPanel: React.FC<{
  label: string;
  isDarkTheme: boolean;
  onJumpToRaw?: () => void;
  headerActions?: React.ReactNode;
  children: React.ReactNode;
}> = ({ label, isDarkTheme, onJumpToRaw, headerActions, children }) => {
  const colors = getViewerColors(isDarkTheme);
  const [isHovered, setIsHovered] = useState(false);

  return (
    <div
      style={{
        border: `1px solid ${colors.inputBorder}`,
        borderRadius: '8px',
        overflow: 'hidden',
        backgroundColor: colors.nestedBackground,
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onDoubleClick={onJumpToRaw ? (event) => {
        event.stopPropagation();
        onJumpToRaw();
      } : undefined}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
          padding: '4px 12px',
          backgroundColor: colors.toolbarBackground,
          borderBottom: `1px solid ${colors.inputBorder}`,
        }}
      >
        <span
          style={{
            fontSize: '11px',
            fontWeight: 600,
            color: colors.mutedText,
            letterSpacing: '0.02em',
            fontFamily: 'var(--vscode-font-family, sans-serif)',
          }}
        >
          {label}
        </span>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
          {headerActions}
          {onJumpToRaw && (
            <HoverActionSlot visible={isHovered}>
              <ActionIconButton
                title="Edit in raw JSON"
                icon="codicon-edit"
                isDarkTheme={isDarkTheme}
                onClick={onJumpToRaw}
              />
            </HoverActionSlot>
          )}
        </div>
      </div>
      <div style={{ padding: '12px' }}>
        {children}
      </div>
    </div>
  );
};

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
      }}
    >
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
  onReplaceDocument?: () => void;
}> = ({ doc, isDarkTheme, onOpenDocument, onReplaceDocument }) => {
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
            justifyContent: 'center',
            gap: '4px',
            height: '30px',
            boxSizing: 'border-box',
            padding: '0 10px',
            border: `1px solid ${colors.inputBorder}`,
            borderRadius: '6px',
            backgroundColor: colors.nestedBackground,
            color: colors.badgeText,
            cursor: 'pointer',
            fontFamily: 'var(--vscode-font-family, sans-serif)',
            fontSize: '13px',
            lineHeight: 1,
          }}
          onClick={(event) => {
            event.stopPropagation();
            onOpenDocument(doc);
          }}
          onDoubleClick={(event) => {
            event.stopPropagation();
          }}
        >
          <i className={`codicon codicon-${iconMap[doc.type]}`} />
          {` Open ${labelMap[doc.type]} (${formatFileSize(doc.size)})`}
        </button>
      )}
      {onReplaceDocument && doc.type !== 'unknown' && (
        <button
          title="Replace file"
          aria-label="Replace file"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '30px',
            height: '30px',
            boxSizing: 'border-box',
            border: `1px solid ${colors.inputBorder}`,
            borderRadius: '6px',
            backgroundColor: colors.nestedBackground,
            color: colors.badgeText,
            cursor: 'pointer',
            lineHeight: 1,
          }}
          onClick={(event) => {
            event.stopPropagation();
            onReplaceDocument();
          }}
          onDoubleClick={(event) => {
            event.stopPropagation();
          }}
        >
          <i className="codicon codicon-folder-opened" />
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
  headerAddon?: React.ReactNode;
  isDarkTheme: boolean;
  depth: number;
  children: React.ReactNode;
  actions?: React.ReactNode;
  onJumpToRaw?: () => void;
  compact?: boolean;
}> = ({ label, badge, headerAddon, isDarkTheme, depth, children, actions, onJumpToRaw, compact = false }) => {
  const colors = getViewerColors(isDarkTheme);
  const title = keyLabelFromPath(label);
  const hasLeadingHeader = Boolean(title || badge || headerAddon);
  const [isHovered, setIsHovered] = useState(false);
  const editAction = onJumpToRaw ? (
    <HoverActionSlot visible={isHovered}>
      <ActionIconButton
        title="Edit in raw JSON"
        icon="codicon-edit"
        isDarkTheme={isDarkTheme}
        onClick={onJumpToRaw}
      />
    </HoverActionSlot>
  ) : null;
  const actionGroup = editAction && actions ? (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
      {editAction}
      {actions}
    </div>
  ) : editAction || actions;

  return (
    <div
      style={{
        marginBottom: '10px',
        marginLeft: depth > 0 ? '12px' : '0',
        position: 'relative',
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onDoubleClick={onJumpToRaw ? (event) => {
        event.stopPropagation();
        onJumpToRaw();
      } : undefined}
    >
      {(hasLeadingHeader || (actionGroup && hasLeadingHeader)) && (
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
            {headerAddon}
          </div>
          {actionGroup}
        </div>
      )}
      {!hasLeadingHeader && actionGroup && (
        <div
          style={{
            position: 'absolute',
            top: compact ? '6px' : '8px',
            right: '8px',
            zIndex: 1,
          }}
        >
          {actionGroup}
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
  onJumpToRaw?: () => void;
}> = ({ label, value, isDarkTheme, depth, onJumpToRaw }) => {
  return (
    <PrettyShell
      label={label}
      badge={getScalarTypeLabel(value)}
      isDarkTheme={isDarkTheme}
      depth={depth}
      onJumpToRaw={onJumpToRaw}
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

const MessageRoleBadge: React.FC<{
  roleStyle: MessageRoleStyle;
  isDarkTheme: boolean;
}> = ({ roleStyle, isDarkTheme }) => {
  const palette = isDarkTheme ? roleStyle.dark : roleStyle.light;

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '1px 7px',
        borderRadius: '999px',
        border: `1px solid ${palette.border}`,
        backgroundColor: palette.background,
        color: palette.text,
        fontSize: '10px',
        lineHeight: '14px',
        fontWeight: 600,
        letterSpacing: '0.01em',
        textTransform: 'lowercase',
        fontFamily: 'var(--vscode-font-family, sans-serif)',
      }}
    >
      {roleStyle.label}
    </span>
  );
};

function formatMessageMetadataValue(value: unknown): string | null {
  const unwrapped = unwrapLosslessNumber(value);
  if (unwrapped === null) {
    return 'null';
  }
  if (typeof unwrapped === 'string') {
    return shouldCollapseLongText(unwrapped) ? getStringPreview(unwrapped, 72) : unwrapped;
  }
  if (typeof unwrapped === 'number' || typeof unwrapped === 'boolean') {
    return String(unwrapped);
  }

  return null;
}

const MessageMetadataStrip: React.FC<{
  metadata: MessageMetadataEntry[];
  isDarkTheme: boolean;
}> = ({ metadata, isDarkTheme }) => {
  const colors = getViewerColors(isDarkTheme);
  const visibleMetadata = metadata
    .map((entry) => ({ ...entry, text: formatMessageMetadataValue(entry.value) }))
    .filter((entry): entry is MessageMetadataEntry & { text: string } => Boolean(entry.text));

  if (visibleMetadata.length === 0) {
    return null;
  }

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '6px',
        marginTop: '10px',
      }}
    >
      {visibleMetadata.map((entry) => (
        <span
          key={entry.path.join('.')}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
            padding: '2px 7px',
            borderRadius: '999px',
            border: `1px solid ${isDarkTheme ? 'rgba(110, 118, 129, 0.18)' : 'rgba(110, 118, 129, 0.12)'}`,
            backgroundColor: isDarkTheme ? 'rgba(110, 118, 129, 0.08)' : 'rgba(110, 118, 129, 0.05)',
            color: colors.mutedText,
            fontSize: '11px',
            lineHeight: '16px',
            fontFamily: 'var(--vscode-font-family, sans-serif)',
          }}
        >
          <span style={{ fontWeight: 600 }}>{entry.key}</span>
          <span>{entry.text}</span>
        </span>
      ))}
    </div>
  );
};

const MessageBubbleBody: React.FC<{
  value: unknown;
  isDarkTheme: boolean;
  depth: number;
  path: string[];
  onReplaceDocument?: (path: string[], doc: DetectedDocument) => void;
  onJumpToRaw?: (path: string[]) => void;
  onOpenDocument?: (doc: DetectedDocument) => void;
  searchQuery?: string;
  currentMatchIndex?: number;
  matchIndexOffset?: number;
  expandPlainText?: boolean;
  suppressArrayHeader?: boolean;
}> = ({ value, isDarkTheme, depth, path, onReplaceDocument, onJumpToRaw, onOpenDocument, searchQuery, currentMatchIndex, matchIndexOffset, expandPlainText = true, suppressArrayHeader = false }) => {
  if (typeof value === 'string') {
    return (
      <PrettyStringNode
        keyName={null}
        value={value}
        isDarkTheme={isDarkTheme}
        depth={depth}
        path={path}
        onReplaceDocument={onReplaceDocument}
        onJumpToRaw={onJumpToRaw}
        onOpenDocument={onOpenDocument}
        searchQuery={searchQuery}
        currentMatchIndex={currentMatchIndex}
        matchIndexOffset={matchIndexOffset}
        expandPlainText={expandPlainText}
      />
    );
  }

  return (
    <PrettyJSONNode
      keyName={null}
      value={value}
      isDarkTheme={isDarkTheme}
      depth={depth}
      path={path}
      siblingData={isRecord(value) ? value : undefined}
      onReplaceDocument={onReplaceDocument}
      onJumpToRaw={onJumpToRaw}
      onOpenDocument={onOpenDocument}
      searchQuery={searchQuery}
      currentMatchIndex={currentMatchIndex}
      matchIndexOffset={matchIndexOffset}
      suppressArrayHeader={suppressArrayHeader}
    />
  );
};

const MessageObjectNode: React.FC<BaseNodeProps & {
  detectedMessage: ReturnType<typeof detectMessageLikeObject>;
}> = ({
  keyName,
  isDarkTheme,
  depth,
  path,
  onReplaceDocument,
  onJumpToRaw,
  onOpenDocument,
  searchQuery,
  currentMatchIndex,
  matchIndexOffset = 0,
  detectedMessage,
}) => {
  if (!detectedMessage) {
    return null;
  }

  const contentBadge = Array.isArray(detectedMessage.content) ? `list · ${detectedMessage.content.length}` : undefined;

  return (
    <PrettyShell
      label={keyName}
      badge={contentBadge}
      headerAddon={<MessageRoleBadge roleStyle={detectedMessage.roleStyle} isDarkTheme={isDarkTheme} />}
      isDarkTheme={isDarkTheme}
      depth={depth}
    >
      <MessageBubbleBody
        value={detectedMessage.content}
        isDarkTheme={isDarkTheme}
        depth={depth + 1}
        path={[...path, ...detectedMessage.contentPath]}
        onReplaceDocument={onReplaceDocument}
        onJumpToRaw={onJumpToRaw}
        onOpenDocument={onOpenDocument}
        searchQuery={searchQuery}
        currentMatchIndex={currentMatchIndex}
        matchIndexOffset={matchIndexOffset}
        suppressArrayHeader
      />
      <MessageMetadataStrip metadata={detectedMessage.metadata} isDarkTheme={isDarkTheme} />
    </PrettyShell>
  );
};

const FlattenedMessageGroupNode: React.FC<BaseNodeProps & {
  group: FlattenedMessageGroup;
}> = ({
  isDarkTheme,
  depth,
  onReplaceDocument,
  onJumpToRaw,
  onOpenDocument,
  searchQuery,
  currentMatchIndex,
  matchIndexOffset = 0,
  group,
}) => {
  if (group.detectedMessages) {
    const detectedMessages = group.detectedMessages;
    const contentBadge = detectedMessages.length === 1 && Array.isArray(detectedMessages[0].content)
      ? `list · ${detectedMessages[0].content.length}`
      : `list · ${detectedMessages.length}`;
    const content = detectedMessages.length === 1 ? (
      <div style={{ display: 'grid', gap: '8px' }}>
        <MessageBubbleBody
          value={detectedMessages[0].content}
          isDarkTheme={isDarkTheme}
          depth={depth + 1}
          path={[group.messageKey, '0', ...detectedMessages[0].contentPath]}
          onReplaceDocument={onReplaceDocument}
          onJumpToRaw={onJumpToRaw}
          onOpenDocument={onOpenDocument}
          searchQuery={searchQuery}
          currentMatchIndex={currentMatchIndex}
          matchIndexOffset={matchIndexOffset}
          suppressArrayHeader
        />
        <MessageMetadataStrip metadata={[...group.metadata, ...detectedMessages[0].metadata]} isDarkTheme={isDarkTheme} />
      </div>
    ) : (
      <div style={{ display: 'grid', gap: '10px' }}>
        {detectedMessages.map((message, index) => (
          <ArrayItemBox
            key={`group-message-${index}`}
            isDarkTheme={isDarkTheme}
            headerAddon={<MessageRoleBadge roleStyle={message.roleStyle} isDarkTheme={isDarkTheme} />}
          >
            <div style={{ display: 'grid', gap: '8px' }}>
              <MessageBubbleBody
                value={message.content}
                isDarkTheme={isDarkTheme}
                depth={depth + 1}
                path={[group.messageKey, String(index), ...message.contentPath]}
                onReplaceDocument={onReplaceDocument}
                onJumpToRaw={onJumpToRaw}
                onOpenDocument={onOpenDocument}
                searchQuery={searchQuery}
                currentMatchIndex={currentMatchIndex}
                matchIndexOffset={matchIndexOffset}
                suppressArrayHeader
              />
              <MessageMetadataStrip metadata={message.metadata} isDarkTheme={isDarkTheme} />
            </div>
          </ArrayItemBox>
        ))}
        <MessageMetadataStrip metadata={group.metadata} isDarkTheme={isDarkTheme} />
      </div>
    );

    return (
      <PrettyShell
        label={group.messageKey}
        badge={contentBadge}
        headerAddon={
          detectedMessages.length === 1
            ? <MessageRoleBadge roleStyle={detectedMessages[0].roleStyle} isDarkTheme={isDarkTheme} />
            : undefined
        }
        isDarkTheme={isDarkTheme}
        depth={depth}
      >
        {content}
      </PrettyShell>
    );
  }

  if (group.detectedMessage) {
    const contentBadge = Array.isArray(group.detectedMessage.content) ? `list · ${group.detectedMessage.content.length}` : undefined;
    return (
      <PrettyShell
        label={group.messageKey}
        badge={contentBadge}
        headerAddon={<MessageRoleBadge roleStyle={group.detectedMessage.roleStyle} isDarkTheme={isDarkTheme} />}
        isDarkTheme={isDarkTheme}
        depth={depth}
      >
        <MessageBubbleBody
          value={group.detectedMessage.content}
          isDarkTheme={isDarkTheme}
          depth={depth + 1}
          path={[group.messageKey, ...group.detectedMessage.contentPath]}
          onReplaceDocument={onReplaceDocument}
          onJumpToRaw={onJumpToRaw}
          onOpenDocument={onOpenDocument}
          searchQuery={searchQuery}
          currentMatchIndex={currentMatchIndex}
          matchIndexOffset={matchIndexOffset}
          suppressArrayHeader
        />
        <MessageMetadataStrip metadata={[...group.metadata, ...group.detectedMessage.metadata]} isDarkTheme={isDarkTheme} />
      </PrettyShell>
    );
  }

  return null;
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
  onJumpToRaw?: () => void;
  searchQuery?: string;
  currentMatchIndex?: number;
  matchIndexOffset?: number;
}> = ({ label, value, isDarkTheme, onJumpToRaw, searchQuery, currentMatchIndex, matchIndexOffset = 0 }) => {
  const colors = getViewerColors(isDarkTheme);
  const isString = typeof value === 'string';
  const [isHovered, setIsHovered] = useState(false);
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
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onDoubleClick={onJumpToRaw ? (event) => {
        event.stopPropagation();
        onJumpToRaw();
      } : undefined}
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
      {onJumpToRaw && (
        <HoverActionSlot visible={isHovered}>
          <ActionIconButton
            title="Edit in raw JSON"
            icon="codicon-edit"
            isDarkTheme={isDarkTheme}
            onClick={onJumpToRaw}
          />
        </HoverActionSlot>
      )}
    </div>
  );
};

const ArrayItemBox: React.FC<{
  isDarkTheme: boolean;
  children: React.ReactNode;
  headerAddon?: React.ReactNode;
  onJumpToRaw?: () => void;
}> = ({ isDarkTheme, children, headerAddon, onJumpToRaw }) => {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <div
      style={{
        border: `1px solid ${isDarkTheme ? 'rgba(110, 118, 129, 0.22)' : 'rgba(110, 118, 129, 0.14)'}`,
        borderRadius: '8px',
        backgroundColor: isDarkTheme ? 'rgba(110, 118, 129, 0.06)' : 'rgba(110, 118, 129, 0.03)',
        padding: '8px 10px',
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onDoubleClick={onJumpToRaw ? (event) => {
        event.stopPropagation();
        onJumpToRaw();
      } : undefined}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', marginBottom: '6px' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>{headerAddon}</div>
        {onJumpToRaw && (
          <HoverActionSlot visible={isHovered}>
            <ActionIconButton
              title="Edit in raw JSON"
              icon="codicon-edit"
              isDarkTheme={isDarkTheme}
              onClick={onJumpToRaw}
            />
          </HoverActionSlot>
        )}
      </div>
      {children}
    </div>
  );
};

const InlineArrayItemRow: React.FC<{
  value: unknown;
  isDarkTheme: boolean;
  onJumpToRaw?: () => void;
  searchQuery?: string;
  currentMatchIndex?: number;
  matchIndexOffset?: number;
}> = ({ value, isDarkTheme, onJumpToRaw, searchQuery, currentMatchIndex, matchIndexOffset = 0 }) => {
  const colors = getViewerColors(isDarkTheme);
  const isString = typeof value === 'string';
  const [isHovered, setIsHovered] = useState(false);
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
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onDoubleClick={onJumpToRaw ? (event) => {
        event.stopPropagation();
        onJumpToRaw();
      } : undefined}
    >
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
      {onJumpToRaw && (
        <HoverActionSlot visible={isHovered}>
          <ActionIconButton
            title="Edit in raw JSON"
            icon="codicon-edit"
            isDarkTheme={isDarkTheme}
            onClick={onJumpToRaw}
          />
        </HoverActionSlot>
      )}
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
  onJumpToRaw?: () => void;
  headerActions?: React.ReactNode;
  searchQuery?: string;
  currentMatchIndex?: number;
  matchIndexOffset?: number;
}> = ({ code, language, isDarkTheme, onJumpToRaw, headerActions, searchQuery, currentMatchIndex, matchIndexOffset = 0 }) => {
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
  const syntaxTheme = withTransparentPrismTheme(prismTheme as unknown as PrismStyleMap);

  return (
    <FramedContentPanel
      label={language.toUpperCase()}
      isDarkTheme={isDarkTheme}
      onJumpToRaw={onJumpToRaw}
      headerActions={headerActions}
    >
      {searchQuery ? (
        <pre
          style={{
            margin: 0,
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
            padding: 0,
            borderRadius: 0,
            background: 'transparent',
            lineHeight: '1.5',
          }}
          codeTagProps={{ style: { background: 'transparent' } }}
          wrapLongLines
        >
          {code}
        </SyntaxHighlighter>
      )}
    </FramedContentPanel>
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

const PrettyStringNode: React.FC<BaseNodeProps & {
  expandPlainText?: boolean;
}> = ({
  keyName,
  value,
  isDarkTheme,
  depth,
  path,
  siblingData,
  onReplaceDocument,
  onJumpToRaw,
  onOpenDocument,
  searchQuery,
  currentMatchIndex,
  matchIndexOffset = 0,
  expandPlainText = false,
}) => {
  const colors = getViewerColors(isDarkTheme);
  const shouldCollapse = shouldCollapseLongText(value);
  const [isExpanded, setIsExpanded] = useState(expandPlainText || !shouldCollapse);
  const [showMarkdownRaw, setShowMarkdownRaw] = useState(false);
  const detectedDoc = onOpenDocument ? detectDocument(value, siblingData) : null;
  const doc = detectedDoc;
  const classification = classifyStringContent(value);
  const canCollapseVisibleText = !expandPlainText && shouldCollapse && classification.kind === 'plain';
  const collapseAction = canCollapseVisibleText ? (
    <ActionIconButton
      title={isExpanded ? 'Collapse' : 'Expand'}
      icon={isExpanded ? 'codicon-chevron-down' : 'codicon-chevron-right'}
      isDarkTheme={isDarkTheme}
      onClick={() => setIsExpanded((current) => !current)}
    />
  ) : undefined;
  const plainStringActions = collapseAction;

  if (doc) {
    return (
      <PrettyShell
        label={keyName}
        badge={doc.type}
        isDarkTheme={isDarkTheme}
        depth={depth}
        onJumpToRaw={onJumpToRaw ? () => onJumpToRaw(path) : undefined}
        compact
      >
        <DocumentButton
          doc={doc}
          isDarkTheme={isDarkTheme}
          onOpenDocument={onOpenDocument}
          onReplaceDocument={onReplaceDocument ? () => onReplaceDocument(path, doc) : undefined}
        />
      </PrettyShell>
    );
  }

  if (classification.kind === 'json' && depth < MAX_PRETTY_DEPTH) {
    return (
      <PrettyShell
        label={keyName}
        badge={classification.label}
        isDarkTheme={isDarkTheme}
        depth={depth}
        onJumpToRaw={onJumpToRaw ? () => onJumpToRaw(path) : undefined}
      >
        <PrettyJSONNode
          keyName={null}
          value={classification.parsed}
          isDarkTheme={isDarkTheme}
          depth={depth + 1}
          path={path}
          onJumpToRaw={undefined}
          onOpenDocument={onOpenDocument}
          searchQuery={searchQuery}
          currentMatchIndex={currentMatchIndex}
          matchIndexOffset={matchIndexOffset}
        />
      </PrettyShell>
    );
  }

  if (classification.kind === 'markdown') {
    return (
      <PrettyShell label={keyName} isDarkTheme={isDarkTheme} depth={depth}>
        <FramedContentPanel
          label="MARKDOWN"
          isDarkTheme={isDarkTheme}
          onJumpToRaw={onJumpToRaw ? () => onJumpToRaw(path) : undefined}
          headerActions={
            <ActionIconButton
              title={showMarkdownRaw ? 'Show rendered markdown' : 'Show raw markdown'}
              icon={<span style={{ fontFamily: 'var(--vscode-editor-font-family, monospace)', fontSize: '11px' }}>{'{}'}</span>}
              isDarkTheme={isDarkTheme}
              active={showMarkdownRaw}
              onClick={() => setShowMarkdownRaw((current) => !current)}
            />
          }
        >
          {showMarkdownRaw ? (
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
              {value}
            </pre>
          ) : (
            <MarkdownRenderer
              markdown={value}
              isDarkTheme={isDarkTheme}
              searchQuery={searchQuery}
              currentMatchIndex={currentMatchIndex}
              matchIndexOffset={matchIndexOffset}
            />
          )}
        </FramedContentPanel>
      </PrettyShell>
    );
  }

  if (classification.kind === 'xml') {
    return (
      <PrettyShell label={keyName} isDarkTheme={isDarkTheme} depth={depth}>
        <CodeBlock
          code={value}
          language="xml"
          isDarkTheme={isDarkTheme}
          onJumpToRaw={onJumpToRaw ? () => onJumpToRaw(path) : undefined}
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
      <PrettyShell label={keyName} isDarkTheme={isDarkTheme} depth={depth}>
        <CodeBlock
          code={code}
          language={classification.language}
          isDarkTheme={isDarkTheme}
          onJumpToRaw={onJumpToRaw ? () => onJumpToRaw(path) : undefined}
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
      isDarkTheme={isDarkTheme}
      depth={depth}
      actions={plainStringActions}
      onJumpToRaw={onJumpToRaw ? () => onJumpToRaw(path) : undefined}
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

const PrettyArrayNode: React.FC<BaseNodeProps & {
  suppressArrayHeader?: boolean;
}> = ({
  keyName,
  value,
  isDarkTheme,
  depth,
  path,
  onReplaceDocument,
  onJumpToRaw,
  onOpenDocument,
  searchQuery,
  currentMatchIndex,
  matchIndexOffset = 0,
  suppressArrayHeader = false,
}) => {
  const colors = getViewerColors(isDarkTheme);
  const [isExpanded, setIsExpanded] = useState(true);
  const arrayValue = value as unknown[];
  const detectedMessages = detectMessageLikeArray(arrayValue);
  const columns = getUniformObjectArrayColumns(arrayValue);
  const singleItem = arrayValue[0];

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
  ) : detectedMessages ? (
    arrayValue.length === 1 ? (
      <div style={{ display: 'grid', gap: '8px' }}>
        <MessageBubbleBody
          value={detectedMessages[0].content}
          isDarkTheme={isDarkTheme}
          depth={depth + 1}
          path={[...path, '0', ...detectedMessages[0].contentPath]}
          onReplaceDocument={onReplaceDocument}
          onJumpToRaw={onJumpToRaw}
          onOpenDocument={onOpenDocument}
          searchQuery={searchQuery}
          currentMatchIndex={currentMatchIndex}
          matchIndexOffset={matchIndexOffset}
          suppressArrayHeader
        />
        <MessageMetadataStrip metadata={detectedMessages[0].metadata} isDarkTheme={isDarkTheme} />
      </div>
    ) : (
      <div style={{ display: 'grid', gap: '10px' }}>
        {detectedMessages.map((message, index) => (
        <ArrayItemBox
          key={`message-${index}`}
          isDarkTheme={isDarkTheme}
          headerAddon={<MessageRoleBadge roleStyle={message.roleStyle} isDarkTheme={isDarkTheme} />}
          >
            <div style={{ display: 'grid', gap: '8px' }}>
              <MessageBubbleBody
                value={message.content}
                isDarkTheme={isDarkTheme}
                depth={depth + 1}
                path={[...path, String(index), ...message.contentPath]}
                onReplaceDocument={onReplaceDocument}
                onJumpToRaw={onJumpToRaw}
                onOpenDocument={onOpenDocument}
                searchQuery={searchQuery}
                currentMatchIndex={currentMatchIndex}
                matchIndexOffset={matchIndexOffset}
                suppressArrayHeader
              />
              <MessageMetadataStrip metadata={message.metadata} isDarkTheme={isDarkTheme} />
            </div>
          </ArrayItemBox>
        ))}
      </div>
    )
  ) : arrayValue.length === 1 ? (
    <PrettyJSONNode
      keyName={null}
      value={singleItem}
      isDarkTheme={isDarkTheme}
      depth={depth + 1}
      path={[...path, '0']}
      siblingData={isRecord(singleItem) ? singleItem : undefined}
      onReplaceDocument={onReplaceDocument}
      onJumpToRaw={onJumpToRaw}
      onOpenDocument={onOpenDocument}
      searchQuery={searchQuery}
      currentMatchIndex={currentMatchIndex}
      matchIndexOffset={matchIndexOffset}
      suppressArrayHeader={suppressArrayHeader}
    />
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
            value={item}
            isDarkTheme={isDarkTheme}
            onJumpToRaw={onJumpToRaw ? () => onJumpToRaw([...path, String(index)]) : undefined}
            searchQuery={searchQuery}
            currentMatchIndex={currentMatchIndex}
            matchIndexOffset={matchIndexOffset}
          />
        ) : (
          <ArrayItemBox
            key={`array-${index}`}
            isDarkTheme={isDarkTheme}
          >
            <PrettyJSONNode
              keyName={null}
              value={item}
              isDarkTheme={isDarkTheme}
              depth={depth + 1}
              path={[...path, String(index)]}
              siblingData={isRecord(item) ? item : undefined}
              onReplaceDocument={onReplaceDocument}
              onJumpToRaw={onJumpToRaw}
              onOpenDocument={onOpenDocument}
              searchQuery={searchQuery}
              currentMatchIndex={currentMatchIndex}
              matchIndexOffset={matchIndexOffset}
              suppressArrayHeader={suppressArrayHeader}
            />
          </ArrayItemBox>
        )
      ))}
    </div>
  );

  if (suppressArrayHeader && keyName === null) {
    return <>{content}</>;
  }

  return (
    <PrettyShell
      label={keyName}
      badge={`list · ${arrayValue.length}`}
      headerAddon={
        detectedMessages && arrayValue.length === 1
          ? <MessageRoleBadge roleStyle={detectedMessages[0].roleStyle} isDarkTheme={isDarkTheme} />
          : undefined
      }
      isDarkTheme={isDarkTheme}
      depth={depth}
      actions={<ActionIconButton title={isExpanded ? 'Collapse' : 'Expand'} icon={isExpanded ? 'codicon-chevron-down' : 'codicon-chevron-right'} isDarkTheme={isDarkTheme} onClick={() => setIsExpanded((current) => !current)} />}
    >
      {content}
    </PrettyShell>
  );
};

const PrettyObjectNode: React.FC<BaseNodeProps & {
  suppressArrayHeader?: boolean;
}> = ({
  keyName,
  value,
  isDarkTheme,
  depth,
  path,
  onReplaceDocument,
  onJumpToRaw,
  onOpenDocument,
  searchQuery,
  currentMatchIndex,
  matchIndexOffset = 0,
  suppressArrayHeader = false,
}) => {
  const entries = Object.entries(value as Record<string, unknown>);
  const detectedMessage = detectMessageLikeObject(value);
  const flattenedGroups = detectFlattenedMessageGroups(value as Record<string, unknown>);
  const groupByMessageKey = new Map(flattenedGroups.map((group) => [group.messageKey, group]));
  const consumedKeys = new Set(flattenedGroups.flatMap((group) => group.consumedKeys));

  if (detectedMessage) {
    return (
      <MessageObjectNode
        keyName={keyName}
        value={value}
        isDarkTheme={isDarkTheme}
        depth={depth}
        path={path}
        siblingData={siblingData}
        onReplaceDocument={onReplaceDocument}
        onJumpToRaw={onJumpToRaw}
        onOpenDocument={onOpenDocument}
        searchQuery={searchQuery}
        currentMatchIndex={currentMatchIndex}
        matchIndexOffset={matchIndexOffset}
        detectedMessage={detectedMessage}
      />
    );
  }

  const objectContent = (
    <div style={{ display: 'grid', gap: '10px' }}>
      {entries.map(([childKey, childValue]) => {
        const group = groupByMessageKey.get(childKey);
        if (group) {
          return (
            <FlattenedMessageGroupNode
              key={childKey}
              keyName={childKey}
              value={childValue}
              isDarkTheme={isDarkTheme}
              depth={depth + 1}
              path={[...path, childKey]}
              siblingData={value as Record<string, unknown>}
              onReplaceDocument={onReplaceDocument}
              onJumpToRaw={onJumpToRaw}
              onOpenDocument={onOpenDocument}
              searchQuery={searchQuery}
              currentMatchIndex={currentMatchIndex}
              matchIndexOffset={matchIndexOffset}
              group={group}
            />
          );
        }

        if (consumedKeys.has(childKey)) {
          return null;
        }

        return isInlineSimpleValue(childValue, value as Record<string, unknown>, Boolean(onOpenDocument)) ? (
          <InlineValueRow
            key={childKey}
            label={childKey}
            value={childValue}
            isDarkTheme={isDarkTheme}
            onJumpToRaw={onJumpToRaw ? () => onJumpToRaw([...path, childKey]) : undefined}
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
            path={[...path, childKey]}
            siblingData={value as Record<string, unknown>}
            onReplaceDocument={onReplaceDocument}
            onJumpToRaw={onJumpToRaw}
              onOpenDocument={onOpenDocument}
              searchQuery={searchQuery}
              currentMatchIndex={currentMatchIndex}
              matchIndexOffset={matchIndexOffset}
              suppressArrayHeader={suppressArrayHeader}
            />
          );
      })}
    </div>
  );

  if (keyName === null) {
    return objectContent;
  }

  return (
    <PrettyShell
      label={keyName}
      badge={`object · ${entries.length}`}
      isDarkTheme={isDarkTheme}
      depth={depth}
    >
      {objectContent}
    </PrettyShell>
  );
};

const PrettyJSONNode: React.FC<BaseNodeProps & {
  suppressArrayHeader?: boolean;
}> = ({
  keyName,
  value,
  isDarkTheme,
  depth,
  path,
  siblingData,
  onReplaceDocument,
  onJumpToRaw,
  onOpenDocument,
  searchQuery,
  currentMatchIndex,
  matchIndexOffset = 0,
  suppressArrayHeader = false,
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
    return (
      <ScalarBox
        label={keyName}
        value={value}
        isDarkTheme={isDarkTheme}
        depth={depth}
        onJumpToRaw={onJumpToRaw && path.length > 0 ? () => onJumpToRaw(path) : undefined}
      />
    );
  }

  if (typeof value === 'string') {
    return (
      <PrettyStringNode
        keyName={keyName}
        value={value}
        isDarkTheme={isDarkTheme}
        depth={depth}
        path={path}
        siblingData={siblingData}
        onReplaceDocument={onReplaceDocument}
        onJumpToRaw={onJumpToRaw}
        onOpenDocument={onOpenDocument}
        searchQuery={searchQuery}
        currentMatchIndex={currentMatchIndex}
        matchIndexOffset={matchIndexOffset}
        suppressArrayHeader={suppressArrayHeader}
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
        path={path}
        onReplaceDocument={onReplaceDocument}
        onJumpToRaw={onJumpToRaw}
        onOpenDocument={onOpenDocument}
        searchQuery={searchQuery}
        currentMatchIndex={currentMatchIndex}
        matchIndexOffset={matchIndexOffset}
        suppressArrayHeader={suppressArrayHeader}
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
        path={path}
        siblingData={siblingData}
        onReplaceDocument={onReplaceDocument}
        onJumpToRaw={onJumpToRaw}
        onOpenDocument={onOpenDocument}
        searchQuery={searchQuery}
        currentMatchIndex={currentMatchIndex}
        matchIndexOffset={matchIndexOffset}
      />
    );
  }

  return (
    <ScalarBox
      label={keyName}
      value={String(value)}
      isDarkTheme={isDarkTheme}
      depth={depth}
      onJumpToRaw={onJumpToRaw && path.length > 0 ? () => onJumpToRaw(path) : undefined}
    />
  );
};

const RawJSONNode: React.FC<BaseNodeProps> = ({
  keyName,
  value,
  isDarkTheme,
  depth,
  path,
  onChange,
  searchQuery,
  currentMatchIndex,
  matchIndexOffset = 0,
  focusRequest,
  onFocusHandled,
}) => {
  const [isExpanded, setIsExpanded] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  const [originalType] = useState<string>(typeof value);
  const colors = getViewerColors(isDarkTheme);
  const headerRef = React.useRef<HTMLDivElement>(null);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const selectionRestoreTimerRef = React.useRef<number | null>(null);

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

    if (isLosslessNumberValue(val)) {
      const numericValue = unwrapLosslessNumber(val);
      return (
        <textarea
          ref={textareaRef}
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
          ref={textareaRef}
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
      if (searchQuery && !isEditing && !editable) {
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
          ref={textareaRef}
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
          ref={textareaRef}
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
          ref={textareaRef}
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

  const scrollElementIntoView = (element: HTMLElement | null) => {
    if (!element) {
      return;
    }

    try {
      element.scrollIntoView({ block: 'center', inline: 'nearest' });
    } catch {
      try {
        element.scrollIntoView();
      } catch {
        // Ignore browser-specific scroll errors.
      }
    }
  };

  const clearSelectionRestoreTimer = React.useCallback(() => {
    if (selectionRestoreTimerRef.current !== null) {
      window.clearTimeout(selectionRestoreTimerRef.current);
      selectionRestoreTimerRef.current = null;
    }
  }, []);

  React.useEffect(() => clearSelectionRestoreTimer, [clearSelectionRestoreTimer]);

  React.useEffect(() => {
    if (!focusRequest || !isExpandable(value)) {
      return;
    }

    if (isProperPathPrefix(path, focusRequest.path) && !isExpanded) {
      setIsExpanded(true);
    }
  }, [focusRequest, isExpanded, path, value]);

  React.useEffect(() => {
    if (!focusRequest || !pathsEqual(path, focusRequest.path)) {
      return;
    }

    console.info('[JSONViewer] resolving focus request', {
      path,
      isExpandable: isExpandable(value),
      valueType: Array.isArray(value) ? 'array' : value === null ? 'null' : typeof value,
    });

    if (isExpandable(value)) {
      setIsExpanded(true);
      requestAnimationFrame(() => {
        scrollElementIntoView(headerRef.current);
        onFocusHandled?.(focusRequest.nonce);
      });
      return;
    }

    requestAnimationFrame(() => {
      const target = textareaRef.current;
      if (!target) {
        onFocusHandled?.(focusRequest.nonce);
        return;
      }

      scrollElementIntoView(target);

      try {
        target.focus();
      } catch {
        onFocusHandled?.(focusRequest.nonce);
        return;
      }

      requestAnimationFrame(() => {
        try {
          clearSelectionRestoreTimer();
          const { start, end, caret } = getTransientSelectionRange(target.value, focusRequest.cursorOffset, focusRequest.selectedText);
          target.setSelectionRange(start, end);
          if (start !== end) {
            const initialSelectionStart = start;
            const initialSelectionEnd = end;
            selectionRestoreTimerRef.current = window.setTimeout(() => {
              if (document.activeElement !== target) {
                selectionRestoreTimerRef.current = null;
                return;
              }

              if (target.selectionStart !== initialSelectionStart || target.selectionEnd !== initialSelectionEnd) {
                selectionRestoreTimerRef.current = null;
                return;
              }

              try {
                target.setSelectionRange(caret, caret);
              } catch {
                // Ignore transient host selection failures.
              }
              selectionRestoreTimerRef.current = null;
            }, 900);
          }
        } catch {
          // Some hosts can reject programmatic selection changes transiently.
        }
        onFocusHandled?.(focusRequest.nonce);
      });
    });
  }, [clearSelectionRestoreTimer, focusRequest, onFocusHandled, path, value]);

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
          <div ref={headerRef} tabIndex={-1} style={{ marginBottom: '2px', outline: 'none' }}>
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
        ref={headerRef}
        tabIndex={-1}
        onClick={toggleExpand}
        style={{
          paddingLeft: `${indent}px`,
          fontFamily: 'var(--vscode-editor-font-family, monospace)',
          fontSize: 'var(--vscode-editor-font-size, 13px)',
          lineHeight: '20px',
          cursor: 'pointer',
          userSelect: 'none',
          outline: 'none',
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
              focusRequest={focusRequest}
              onFocusHandled={onFocusHandled}
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
  viewMode: controlledViewMode,
  onViewModeChange,
  hideViewToggle = false,
  containerPadding = '12px',
  containerBackgroundColor = 'var(--vscode-editor-background)',
  scrollMode = 'internal',
}) => {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const lastSelectionRef = React.useRef<SelectionSnapshot>({ cursorOffset: null, selectedText: null });
  const [internalViewMode, setInternalViewMode] = React.useState<ViewMode>(defaultViewMode);
  const [focusRequest, setFocusRequest] = React.useState<FocusRequest | null>(null);
  const viewMode = controlledViewMode ?? internalViewMode;

  const setViewMode = React.useCallback((next: ViewMode) => {
    if (controlledViewMode === undefined) {
      setInternalViewMode(next);
    }
    onViewModeChange?.(next);
  }, [controlledViewMode, onViewModeChange]);

  const captureSelectionSnapshot = React.useCallback(() => {
    lastSelectionRef.current = {
      cursorOffset: getSelectionLeafOffset(),
      selectedText: getSelectionLeafText(),
    };
  }, []);

  const handleChange = (path: string[], newValue: any) => {
    if (!onChange) {
      return;
    }

    if (path.length === 0) {
      onChange(newValue);
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

  const requestReplacementDocumentFromHost = React.useCallback(async (doc: DetectedDocument): Promise<ReplacementDocumentFile | null> => {
    if (!window.vscode) {
      return pickReplacementDocumentFromBrowser(doc.type);
    }

    const requestId = `replace-doc-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    return new Promise((resolve) => {
      const handleMessage = (event: MessageEvent) => {
        const message = event.data;
        if (message?.type !== 'replacementDocumentPicked' || message?.payload?.requestId !== requestId) {
          return;
        }

        window.removeEventListener('message', handleMessage);
        const payload = message.payload as {
          cancelled?: boolean;
          data?: string;
          fileName?: string;
          mimeType?: string;
        };

        if (payload.cancelled || !payload.data || !payload.fileName) {
          resolve(null);
          return;
        }

        const mimeType = payload.mimeType || '';
        resolve({
          data: payload.data,
          name: payload.fileName,
          mimeType,
          type: inferDocumentTypeFromMimeOrName(mimeType, payload.fileName),
        });
      };

      window.addEventListener('message', handleMessage);
      window.vscode?.postMessage({
        type: 'pickReplacementDocument',
        payload: {
          requestId,
          expectedType: doc.type,
        },
      });
    });
  }, []);

  const handleReplaceDocument = React.useCallback(async (path: string[], doc: DetectedDocument) => {
    if (!onChange) {
      return;
    }

    const replacement = await requestReplacementDocumentFromHost(doc);
    if (!replacement) {
      return;
    }

    try {
      const newData = applyDocumentReplacement(data, path, replacement);
      onChange(newData);
    } catch (error) {
      console.warn('[JSONViewer] Failed to replace document', error);
    }
  }, [data, onChange, requestReplacementDocumentFromHost]);

  const handleJumpToRaw = React.useCallback((path: string[]) => {
    const liveCursorOffset = getSelectionLeafOffset();
    const liveSelectedText = getSelectionLeafText();
    const cursorOffset = liveCursorOffset ?? lastSelectionRef.current.cursorOffset;
    const selectedText = liveSelectedText ?? lastSelectionRef.current.selectedText;
    console.info('[JSONViewer] jump to raw requested', {
      path,
      cursorOffset,
      selectedText,
      dataType: Array.isArray(data) ? 'array' : data === null ? 'null' : typeof data,
    });
    setViewMode('raw');
    setFocusRequest({
      path,
      nonce: Date.now() + Math.random(),
      cursorOffset,
      selectedText,
    });
  }, [data]);

  const handleFocusHandled = React.useCallback((nonce: number) => {
    setFocusRequest((current) => (current?.nonce === nonce ? null : current));
  }, []);

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
      onReplaceDocument={onChange ? handleReplaceDocument : undefined}
      onJumpToRaw={onChange ? handleJumpToRaw : undefined}
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
              focusRequest={focusRequest}
              onFocusHandled={handleFocusHandled}
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
        focusRequest={focusRequest}
        onFocusHandled={handleFocusHandled}
        searchQuery={searchQuery}
        currentMatchIndex={currentMatchIndex}
        matchIndexOffset={0}
      />
    );
  };

  return (
    <div
      ref={containerRef}
      onMouseUpCapture={captureSelectionSnapshot}
      onKeyUpCapture={captureSelectionSnapshot}
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: scrollMode === 'internal' ? '100%' : 'auto',
        minHeight: 0,
        overflow: scrollMode === 'internal' ? 'auto' : 'visible',
        padding: containerPadding,
        backgroundColor: containerBackgroundColor,
      }}
    >
      {!hideViewToggle && (
        <div
          style={{
            position: 'sticky',
            top: '8px',
            zIndex: 2,
            alignSelf: 'flex-end',
            marginLeft: 'auto',
            marginBottom: '8px',
            padding: '4px',
            borderRadius: '10px',
            backgroundColor: isDarkTheme ? 'rgba(30, 30, 30, 0.82)' : 'rgba(255, 255, 255, 0.88)',
            boxShadow: isDarkTheme
              ? '0 4px 14px rgba(0, 0, 0, 0.22)'
              : '0 4px 14px rgba(15, 23, 42, 0.08)',
            backdropFilter: 'blur(8px)',
          }}
        >
          <ViewerToggle
            viewMode={viewMode}
            onChange={setViewMode}
            isDarkTheme={isDarkTheme}
            editable={onChange !== undefined}
          />
        </div>
      )}
      {viewMode === 'pretty' ? renderPrettyRoot() : renderRawRoot()}
    </div>
  );
};
