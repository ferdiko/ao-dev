import React, { useState } from 'react';
import { parse, stringify } from 'lossless-json';
import { detectDocument, formatFileSize, getDocumentKey, DetectedDocument } from '../utils/documentDetection';
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
}

interface JSONNodeProps {
  keyName: string | null;
  value: any;
  isDarkTheme: boolean;
  depth: number;
  isLast: boolean;
  path: string[];
  onChange?: (path: string[], newValue: any) => void;
  siblingData?: Record<string, unknown>;
  onOpenDocument?: (doc: DetectedDocument) => void;
  searchQuery?: string;
  currentMatchIndex?: number;
  matchIndexOffset: number;
}

const JSONNode: React.FC<JSONNodeProps> = ({ keyName, value, isDarkTheme, depth, isLast, path, onChange, siblingData, onOpenDocument, searchQuery, currentMatchIndex, matchIndexOffset }) => {
  // Expand everything by default
  const [isExpanded, setIsExpanded] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  // Track the original type to preserve it during editing
  const [originalType] = useState<string>(typeof value);
  // Toggle to show raw base64 instead of document button
  const [showRawDocument, setShowRawDocument] = useState(false);
  // Get opened document paths from context
  const { openedPaths } = useDocumentContext();

  // Use VS Code CSS variables for theme-aware colors
  // Syntax highlighting colors use VS Code's token colors with fallbacks
  const colors = {
    key: 'var(--vscode-symbolIcon-propertyForeground, #9cdcfe)',
    string: 'var(--vscode-debugTokenExpression-string, #ce9178)',
    number: 'var(--vscode-debugTokenExpression-number, #b5cea8)',
    boolean: 'var(--vscode-debugTokenExpression-boolean, #569cd6)',
    null: 'var(--vscode-debugTokenExpression-boolean, #569cd6)',
    bracket: 'var(--vscode-foreground)',
    background: 'var(--vscode-editor-background)',
    hoverBackground: 'var(--vscode-list-hoverBackground)',
    inputBackground: 'var(--vscode-input-background)',
    inputBorder: 'var(--vscode-input-border, var(--vscode-panel-border))',
  };

  const indent = depth * 15;

  // Helper to highlight text with search matches
  const highlightText = (text: string, query: string, startIndex: number, currentMatch: number): { element: React.ReactNode; matchCount: number } => {
    if (!query || !text) return { element: text, matchCount: 0 };

    const lowerText = text.toLowerCase();
    const lowerQuery = query.toLowerCase();
    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let matchIndex = startIndex;
    let matchCount = 0;

    let pos = 0;
    while ((pos = lowerText.indexOf(lowerQuery, lastIndex)) !== -1) {
      // Add text before match
      if (pos > lastIndex) {
        parts.push(text.substring(lastIndex, pos));
      }

      // Add highlighted match
      const isCurrentMatch = matchIndex === currentMatch;
      const matchText = text.substring(pos, pos + query.length);
      parts.push(
        <span
          key={`match-${matchIndex}`}
          data-match-index={matchIndex}
          style={{
            backgroundColor: isCurrentMatch ? '#f0a020' : '#ffff00',
            color: '#000000',
            borderRadius: '2px',
            padding: '0 1px',
          }}
        >
          {matchText}
        </span>
      );

      matchIndex++;
      matchCount++;
      lastIndex = pos + query.length;
    }

    // Add remaining text
    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex));
    }

    return { element: parts.length > 0 ? <>{parts}</> : text, matchCount };
  };

  // Check if a value is a LosslessNumber from lossless-json library
  const isLosslessNumber = (val: any): boolean => {
    return val !== null && typeof val === 'object' && val.isLosslessNumber === true;
  };

  // Get the actual value, unwrapping LosslessNumber if needed
  const unwrapValue = (val: any): any => {
    if (isLosslessNumber(val)) {
      return Number(val.value);
    }
    return val;
  };

  const isExpandable = (val: any) => {
    // LosslessNumber objects should not be expandable - they're just numbers
    if (isLosslessNumber(val)) {
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

  const parseEditValue = (editVal: string): any => {
    const trimmed = editVal.trim();

    // If the original value was a string, keep it as a string
    if (originalType === 'string') {
      return editVal;
    }

    // Try to parse as JSON literal
    if (trimmed === 'null') {
      return null;
    } else if (trimmed === 'true') {
      return true;
    } else if (trimmed === 'false') {
      return false;
    } else if (!isNaN(Number(trimmed)) && trimmed !== '') {
      // Number - lossless-json will preserve float vs int distinction
      return Number(trimmed);
    } else {
      // String - return as-is, lossless-json handles type preservation
      return editVal;
    }
  };

  const saveEdit = () => {
    if (!onChange) return;
    const newValue = parseEditValue(editValue);
    onChange(path, newValue);
    setIsEditing(false);
  };

  const handleChange = (newEditValue: string) => {
    setEditValue(newEditValue);
    if (!isEditing) setIsEditing(true);

    // Immediately propagate changes to parent for change detection
    if (onChange) {
      const newValue = parseEditValue(newEditValue);
      onChange(path, newValue);
    }
  };

  const cancelEdit = () => {
    setIsEditing(false);
    setEditValue('');
  };

  const renderValue = (val: any) => {
    const editable = onChange !== undefined;

    const getTextareaStyle = (color: string) => ({
      fontFamily: 'var(--vscode-editor-font-family, monospace)',
      fontSize: 'var(--vscode-editor-font-size, 13px)',
      padding: '2px 4px',
      border: `1px solid ${colors.inputBorder}`,
      borderRadius: '2px',
      backgroundColor: colors.inputBackground,
      color: color,
      outline: 'none',
      width: '100%',
      resize: 'both' as const,
      lineHeight: '1.4',
      overflow: 'auto',
      cursor: editable ? 'text' : 'default',
      boxSizing: 'border-box' as const,
    });

    // Calculate rows based on content length
    const getRows = (content: string) => {
      if (content.length < 100) return 1;
      if (content.length < 500) return 5;
      if (content.length < 2000) return 15;
      return 30;
    };

    // Check for base64-encoded documents (PDF, images, etc.)
    if (typeof val === 'string' && onOpenDocument && !showRawDocument) {
      const doc = detectDocument(val, siblingData);
      if (doc) {
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
          zip: 'file-zip',
          unknown: 'file-binary',
        };

        const buttonStyle: React.CSSProperties = {
          display: 'inline-flex',
          alignItems: 'center',
          gap: '4px',
          padding: '4px 8px',
          border: `1px solid ${colors.inputBorder}`,
          borderRadius: '4px',
          backgroundColor: isDarkTheme ? '#2d2d2d' : '#f3f3f3',
          color: isDarkTheme ? '#cccccc' : '#333333',
          cursor: 'pointer',
          fontFamily: 'var(--vscode-font-family, sans-serif)',
          fontSize: 'var(--vscode-font-size, 13px)',
        };

        const linkStyle: React.CSSProperties = {
          background: 'none',
          border: 'none',
          color: isDarkTheme ? '#569cd6' : '#0451a5',
          cursor: 'pointer',
          textDecoration: 'underline',
          fontFamily: 'var(--vscode-font-family, sans-serif)',
          fontSize: 'var(--vscode-font-size, 13px)',
          padding: '4px',
        };

        const pathStyle: React.CSSProperties = {
          fontFamily: 'var(--vscode-editor-font-family, monospace)',
          fontSize: 'var(--vscode-editor-font-size, 12px)',
          color: isDarkTheme ? '#888888' : '#666666',
        };

        // Use friendly label - "Open file" for zip/unknown since we can't distinguish DOCX/XLSX/etc
        const labelMap: Record<string, string> = {
          pdf: 'PDF',
          png: 'PNG',
          jpeg: 'JPEG',
          gif: 'GIF',
          webp: 'WebP',
          docx: 'DOCX',
          xlsx: 'XLSX',
          zip: 'file',
          unknown: 'file',
        };

        return (
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <button style={buttonStyle} onClick={() => onOpenDocument(doc)}>
              <i className={`codicon codicon-${iconMap[doc.type]}`} />
              {` Open ${labelMap[doc.type]} (${formatFileSize(doc.size)})`}
            </button>
            {openedPath && (
              <span style={pathStyle}>File available at {openedPath}</span>
            )}
            <button style={linkStyle} onClick={() => setShowRawDocument(true)}>
              Show raw
            </button>
          </div>
        );
      }
    }

    // Handle LosslessNumber objects - render them as regular numbers
    if (isLosslessNumber(val)) {
      const numValue = unwrapValue(val);
      return (
        <textarea
          rows={getRows(numValue.toString())}
          value={isEditing ? editValue : numValue.toString()}
          onChange={(e) => handleChange(e.target.value)}
          onFocus={() => {
            if (!isEditing) {
              setEditValue(numValue.toString());
              setIsEditing(true);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              cancelEdit();
            } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
              e.preventDefault();
              saveEdit();
            }
          }}
          readOnly={!editable}
          style={getTextareaStyle(colors.number)}
        />
      );
    }
    // Always display values in a textarea for editability
    if (val === null) {
      return (
        <textarea
          rows={getRows('null')}
          value={editValue || 'null'}
          onChange={(e) => handleChange(e.target.value)}
          onFocus={() => {
            if (!isEditing) {
              setEditValue('null');
              setIsEditing(true);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              cancelEdit();
            } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
              e.preventDefault();
              saveEdit();
            }
          }}
          readOnly={!editable}
          style={getTextareaStyle(colors.null)}
        />
      );
    }
    if (typeof val === 'string') {
      // Display strings directly - lossless-json preserves types
      const displayValue = isEditing ? editValue : val;

      // If searching and not editing, show highlighted text
      if (searchQuery && !isEditing) {
        const { element: highlighted } = highlightText(val, searchQuery, matchIndexOffset, currentMatchIndex ?? -1);

        const preStyle: React.CSSProperties = {
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
        };

        return (
          <pre
            style={preStyle}
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
          onChange={(e) => handleChange(e.target.value)}
          onFocus={() => {
            if (!isEditing) {
              setEditValue(val);
              setIsEditing(true);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              cancelEdit();
            } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
              e.preventDefault();
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
          rows={getRows(val.toString())}
          value={isEditing ? editValue : val.toString()}
          onChange={(e) => handleChange(e.target.value)}
          onFocus={() => {
            if (!isEditing) {
              setEditValue(val.toString());
              setIsEditing(true);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              cancelEdit();
            } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
              e.preventDefault();
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
          rows={getRows(val.toString())}
          value={isEditing ? editValue : val.toString()}
          onChange={(e) => handleChange(e.target.value)}
          onFocus={() => {
            if (!isEditing) {
              setEditValue(val.toString());
              setIsEditing(true);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              cancelEdit();
            } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
              e.preventDefault();
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
      setIsExpanded(!isExpanded);
    }
  };

  if (!isExpandable(value)) {
    // Simple value - render with key above textarea
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
            <span style={{ color: colors.key }}>"{keyName?.split('.').pop() || keyName}"</span>
            <span style={{ color: colors.bracket }}>:</span>
          </div>
        )}
        <div>
          {renderValue(value)}
        </div>
      </div>
    );
  }

  // Complex value - render with expand/collapse
  const isArray = Array.isArray(value);
  const entries = isArray ? value.map((v, i) => [i.toString(), v]) : Object.entries(value);

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
        onMouseEnter={(e) => {
          e.currentTarget.style.backgroundColor = colors.hoverBackground;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundColor = 'transparent';
        }}
      >
        <i
          className={`codicon ${isExpanded ? 'codicon-chevron-down' : 'codicon-chevron-right'}`}
          style={{ marginRight: '4px', fontSize: '16px' }}
        />
        {keyName !== null && (
          <>
            <span style={{ color: colors.key }}>"{keyName?.split('.').pop() || keyName}"</span>
            <span style={{ color: colors.bracket }}>: </span>
          </>
        )}
        <span style={{ color: colors.bracket }}>
          {isArray ? '[' : '{'}
          {!isExpanded && (
            <>
              <span style={{ color: colors.bracket, opacity: 0.6 }}>
                {getValuePreview(value)}
              </span>
              {isArray ? ']' : '}'}
            </>
          )}
        </span>
      </div>

      {isExpanded && (
        <>
          {entries.map(([key, val], index) => (
            <JSONNode
              key={key}
              keyName={isArray ? null : key}
              value={val}
              isDarkTheme={isDarkTheme}
              depth={depth + 1}
              isLast={index === entries.length - 1}
              path={[...path, key]}
              onChange={onChange}
              siblingData={isArray ? undefined : value}
              onOpenDocument={onOpenDocument}
              searchQuery={searchQuery}
              currentMatchIndex={currentMatchIndex}
              matchIndexOffset={0}
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

export const JSONViewer: React.FC<JSONViewerProps> = ({ data, isDarkTheme, depth = 0, onChange, onOpenDocument, searchQuery, currentMatchIndex, onMatchCountChange }) => {
  const containerRef = React.useRef<HTMLDivElement>(null);

  const handleChange = (path: string[], newValue: any) => {
    if (!onChange) return;

    // Clone the data and update the value at the specified path using lossless-json
    const newData = parse(stringify(data) || '{}') as any;
    let current: any = newData;

    for (let i = 0; i < path.length - 1; i++) {
      current = current[path[i]];
    }

    current[path[path.length - 1]] = newValue;
    onChange(newData);
  };

  // Count matches and scroll to current match when search changes
  React.useEffect(() => {
    if (!containerRef.current || !searchQuery) {
      onMatchCountChange?.(0);
      return;
    }

    // Use setTimeout to allow DOM to render first
    setTimeout(() => {
      const matches = containerRef.current?.querySelectorAll('[data-match-index]') || [];
      onMatchCountChange?.(matches.length);

      // Scroll to current match
      if (currentMatchIndex !== undefined && currentMatchIndex >= 0 && currentMatchIndex < matches.length) {
        const currentMatch = matches[currentMatchIndex];
        currentMatch?.scrollIntoView({ behavior: 'smooth', block: 'center' });

        // Update highlight colors - current match is orange, others are yellow
        matches.forEach((match, i) => {
          (match as HTMLElement).style.backgroundColor = i === currentMatchIndex ? '#f0a020' : '#ffff00';
        });
      }
    }, 0);
  }, [searchQuery, currentMatchIndex, data, onMatchCountChange]);

  // If data is an object or array, render its children directly without the wrapper
  const isObject = data !== null && typeof data === 'object' && !Array.isArray(data);
  const isArray = Array.isArray(data);

  return (
    <div
      ref={containerRef}
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'auto',
        padding: '12px',
        backgroundColor: 'var(--vscode-editor-background)',
      }}
    >
      {(isObject || isArray) ? (
        // Render children directly, starting at depth -1 so first level is depth 0
        <>
          {Object.entries(data).map(([key, val], index, arr) => (
            <JSONNode
              key={key}
              keyName={isArray ? null : key}
              value={val}
              isDarkTheme={isDarkTheme}
              depth={0}
              isLast={index === arr.length - 1}
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
      ) : (
        // For primitive values, render normally
        <JSONNode
          keyName={null}
          value={data}
          isDarkTheme={isDarkTheme}
          depth={depth}
          isLast={true}
          path={[]}
          onChange={onChange ? handleChange : undefined}
          onOpenDocument={onOpenDocument}
          searchQuery={searchQuery}
          currentMatchIndex={currentMatchIndex}
          matchIndexOffset={0}
        />
      )}
    </div>
  );
};
