import React, { useState, useEffect } from 'react';
import { JSONViewer } from '../JSONViewer';
import { parse, stringify } from 'lossless-json';
import { DetectedDocument } from '../../utils/documentDetection';

interface NodeEditModalProps {
  nodeId: string;
  field: 'input' | 'output';
  label: string;
  value: string;
  isDarkTheme: boolean;
  onClose: () => void;
  onSave: (nodeId: string, field: string, value: string) => void;
  onOpenDocument?: (doc: DetectedDocument) => void;
}

/**
 * Shape of the stored node JSON value.
 * `raw` must be preserved exactly.
 * `to_show` is the editable/displayed portion.
 */
interface NodeStoredValue {
  raw: string;
  to_show: unknown;
}

/**
 * lossless-json stringify can return undefined.
 * Normalize it to always return a string.
 */
const safeStringify = (
  value: unknown,
  replacer?: Parameters<typeof stringify>[1],
  space?: Parameters<typeof stringify>[2]
): string => {
  return stringify(value, replacer, space) ?? '';
};

export const NodeEditModal: React.FC<NodeEditModalProps> = ({
  nodeId,
  field,
  label,
  value: initialValue,
  isDarkTheme,
  onClose,
  onSave,
  onOpenDocument
}) => {
  /**
   * Extracts and pretty-prints the `to_show` field if present.
   * Falls back to the raw string if parsing fails.
   */
  const getDisplayValue = (jsonStr: string): string => {
    try {
      const parsed = parse(jsonStr);
      if (parsed && typeof parsed === 'object' && 'to_show' in parsed) {
        return safeStringify((parsed as NodeStoredValue).to_show, null, 2);
      }
    } catch {
      // fall through
    }
    return jsonStr;
  };

  const [currentValue, setCurrentValue] = useState<string>(
    getDisplayValue(initialValue)
  );
  const [hasChanges, setHasChanges] = useState(false);
  const [parsedData, setParsedData] = useState<unknown>(null);
  const [initialParsedData, setInitialParsedData] = useState<unknown>(null);

  /**
   * Reset state when the initial value changes.
   */
  useEffect(() => {
    setCurrentValue(getDisplayValue(initialValue));
    setHasChanges(false);

    try {
      const parsed = parse(getDisplayValue(initialValue));
      setParsedData(parsed);
      setInitialParsedData(parse(safeStringify(parsed))); // deep clone
    } catch {
      setParsedData(null);
      setInitialParsedData(null);
    }
  }, [initialValue]);

  /**
   * Detect changes via deep comparison.
   */
  useEffect(() => {
    if (parsedData === null || initialParsedData === null) {
      setHasChanges(false);
      return;
    }

    const currentStr = safeStringify(parsedData);
    const initialStr = safeStringify(initialParsedData);
    setHasChanges(currentStr !== initialStr);
  }, [parsedData, initialParsedData]);

  const handleJSONChange = (newData: unknown) => {
    setParsedData(newData);
    setCurrentValue(safeStringify(newData, null, 2));
  };

  /**
   * Keyboard shortcuts
   */
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      } else if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        handleSave();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [currentValue, hasChanges]);

  /**
   * Save handler
   * Reconstructs `{ raw, to_show }` while preserving `raw`.
   */
  const handleSave = () => {
    let valueToSave = currentValue;

    try {
      const originalParsed = parse(initialValue) as NodeStoredValue;

      if (
        originalParsed &&
        typeof originalParsed === 'object' &&
        'to_show' in originalParsed
      ) {
        const editedToShow = parse(currentValue);

        const reconstructed: NodeStoredValue = {
          raw: originalParsed.raw, // preserve exactly
          to_show: editedToShow
        };

        valueToSave = safeStringify(reconstructed);
      }
    } catch {
      valueToSave = currentValue;
    }

    onSave(nodeId, field, valueToSave);
    onClose();
  };

  const handleReset = () => {
    setCurrentValue(getDisplayValue(initialValue));
  };

  return (
    <div
      style={{
        margin: 0,
        padding: 0,
        fontFamily:
          'var(--vscode-font-family, "Segoe UI", "Helvetica Neue", Arial, sans-serif)',
        fontSize: 'var(--vscode-font-size, 13px)',
        color: isDarkTheme ? '#cccccc' : '#333333',
        background: isDarkTheme ? '#1e1e1e' : '#ffffff',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden'
      }}
    >
      <div
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          backgroundColor: isDarkTheme ? '#1e1e1e' : '#ffffff',
          borderBottom: `1px solid ${
            isDarkTheme ? '#3c3c3c' : '#d0d0d0'
          }`,
          padding: '12px 16px',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <h2
            style={{
              margin: 0,
              fontSize: 'var(--vscode-font-size, 13px)',
              fontWeight: 'normal',
              color: isDarkTheme ? '#ffffff' : '#000000'
            }}
          >
            Edit {label} {field === 'input' ? 'Input' : 'Output'}
          </h2>

          <button
            onClick={handleSave}
            disabled={!hasChanges}
            title="Save (Cmd+S / Ctrl+S)"
            style={{
              background: 'none',
              border: 'none',
              padding: '4px',
              cursor: hasChanges ? 'pointer' : 'not-allowed',
              opacity: hasChanges ? 1 : 0.5,
              color: isDarkTheme ? '#ffffff' : '#000000'
            }}
          >
            💾
          </button>
        </div>

        <button
          onClick={onClose}
          title="Cancel (ESC)"
          style={{
            background: 'none',
            border: 'none',
            padding: '4px',
            cursor: 'pointer',
            color: isDarkTheme ? '#ffffff' : '#000000'
          }}
        >
          ✕
        </button>
      </div>

      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
          overflow: 'auto'
        }}
      >
        {parsedData !== null ? (
          <JSONViewer data={parsedData} isDarkTheme={isDarkTheme} onChange={handleJSONChange} onOpenDocument={onOpenDocument} />
        ) : (
          <div
            style={{
              padding: '12px',
              fontFamily:
                'var(--vscode-editor-font-family, monospace)',
              fontSize:
                'var(--vscode-editor-font-size, 13px)'
            }}
          >
            Unable to parse JSON data
          </div>
        )}
      </div>

      <div
        style={{
          fontSize: '11px',
          color: isDarkTheme ? '#858585' : '#6c6c6c',
          margin: '8px 0',
          textAlign: 'center'
        }}
      >
        Press ESC to cancel •{' '}
        {navigator.platform.toLowerCase().includes('mac')
          ? '⌘S'
          : 'Ctrl+S'}{' '}
        to save
      </div>
    </div>
  );
};
