import React, { useState, useEffect, useRef } from 'react';
import { useIsVsCodeDarkTheme } from '@sovara/shared-components/utils/themeUtils';
import { JSONViewer } from '@sovara/shared-components/components/JSONViewer';

interface NodeEditModalProps {
  nodeId: string;
  field: 'input' | 'output';
  label: string;
  value: string;
  onClose: () => void;
  onSave: (nodeId: string, field: string, value: string) => void;
}

export const NodeEditModal: React.FC<NodeEditModalProps> = ({
  nodeId,
  field,
  label,
  value: initialValue,
  onClose,
  onSave
}) => {
  const [currentValue, setCurrentValue] = useState(initialValue);
  const [savedValue, setSavedValue] = useState(initialValue);
  const [hasChanges, setHasChanges] = useState(false);
  const isDarkTheme = useIsVsCodeDarkTheme();
  const [parsedData, setParsedData] = useState<any>(null);

  useEffect(() => {
    setCurrentValue(initialValue);
    setSavedValue(initialValue);
    setHasChanges(false);

    try {
      setParsedData(JSON.parse(initialValue));
    } catch (e) {
      setParsedData(null);
    }
  }, [initialValue]);

  useEffect(() => {
    // Normalize JSON strings for comparison (remove whitespace differences)
    const normalizeJSON = (str: string) => {
      try {
        return JSON.stringify(JSON.parse(str));
      } catch {
        return str;
      }
    };

    const hasChanged = normalizeJSON(currentValue) !== normalizeJSON(savedValue);
    setHasChanges(hasChanged);
  }, [currentValue, savedValue]);

  const handleJSONChange = (newData: any) => {
    // Update both the parsed data and the string value
    setParsedData(newData);
    setCurrentValue(JSON.stringify(newData, null, 2));
  };

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
  }, [hasChanges, currentValue]);

  const handleSave = () => {
    onSave(nodeId, field, currentValue);
    setSavedValue(currentValue);
  };

  const handleReset = () => {
    setCurrentValue(getDisplayValue(initialValue));
  };

  return (
    <div
      style={{
        margin: 0,
        padding: 0,
        fontFamily: 'var(--vscode-font-family)',
        fontSize: 'var(--vscode-font-size)',
        color: 'var(--vscode-foreground)',
        background: 'var(--vscode-editor-background)',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          backgroundColor: 'var(--vscode-editor-background)',
          borderBottom: `1px solid ${isDarkTheme ? '#3c3c3c' : '#d0d0d0'}`,
          padding: '12px 16px',
          flexShrink: 0,
        }}
      >
        <h2
          style={{
            margin: 0,
            fontSize: 'var(--vscode-font-size)',
            fontWeight: 'normal',
            color: 'var(--vscode-editor-foreground)',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          Edit {label} {field === 'input' ? 'Input' : 'Output'}
          {hasChanges && (
            <div
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: isDarkTheme ? '#ffffff' : '#000000',
                flexShrink: 0,
              }}
            />
          )}
        </h2>
      </div>

      <div style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        overflow: 'auto',
      }}>
        {parsedData !== null ? (
          <JSONViewer data={parsedData} isDarkTheme={isDarkTheme} onChange={handleJSONChange} />
        ) : (
          <div style={{
            padding: '12px',
            color: 'var(--vscode-foreground)',
            fontFamily: 'var(--vscode-editor-font-family, monospace)',
            fontSize: 'var(--vscode-editor-font-size, 13px)',
          }}>
            Unable to parse JSON data
          </div>
        )}
      </div>
    </div>
  );
};