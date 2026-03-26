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

interface ViewerCrashDetails {
  source: 'react' | 'window.error' | 'unhandledrejection';
  message: string;
  stack?: string;
  componentStack?: string;
}

class ViewerErrorBoundary extends React.Component<
  {
    isDarkTheme: boolean;
    onCrash: (details: ViewerCrashDetails) => void;
    children: React.ReactNode;
  },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    this.props.onCrash({
      source: 'react',
      message: error.message,
      stack: error.stack,
      componentStack: info.componentStack,
    });
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            margin: '12px',
            padding: '12px',
            borderRadius: '8px',
            border: `1px solid ${this.props.isDarkTheme ? '#7f1d1d' : '#fecaca'}`,
            backgroundColor: this.props.isDarkTheme ? 'rgba(127, 29, 29, 0.18)' : '#fef2f2',
            color: this.props.isDarkTheme ? '#fecaca' : '#991b1b',
            fontSize: '12px',
            lineHeight: '1.5',
          }}
        >
          JSON viewer crashed. Diagnostic details are shown below.
        </div>
      );
    }

    return this.props.children;
  }
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
  const [viewerCrash, setViewerCrash] = useState<ViewerCrashDetails | null>(null);

  useEffect(() => {
    setCurrentValue(initialValue);
    setSavedValue(initialValue);
    setHasChanges(false);
    setViewerCrash(null);

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
    const handleWindowError = (event: ErrorEvent) => {
      const details: ViewerCrashDetails = {
        source: 'window.error',
        message: event.message || String(event.error || 'Unknown error'),
        stack: event.error instanceof Error ? event.error.stack : undefined,
      };
      console.error('[NodeEditModal] window.error', details);
      setViewerCrash(details);
    };

    const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason;
      const details: ViewerCrashDetails = {
        source: 'unhandledrejection',
        message:
          reason instanceof Error
            ? reason.message
            : typeof reason === 'string'
              ? reason
              : JSON.stringify(reason),
        stack: reason instanceof Error ? reason.stack : undefined,
      };
      console.error('[NodeEditModal] unhandledrejection', details);
      setViewerCrash(details);
    };

    window.addEventListener('error', handleWindowError);
    window.addEventListener('unhandledrejection', handleUnhandledRejection);
    return () => {
      window.removeEventListener('error', handleWindowError);
      window.removeEventListener('unhandledrejection', handleUnhandledRejection);
    };
  }, []);

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
    if (!hasChanges) {
      return;
    }

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
        {viewerCrash && (
          <div
            style={{
              margin: '12px',
              padding: '12px',
              borderRadius: '8px',
              border: `1px solid ${isDarkTheme ? '#7f1d1d' : '#fecaca'}`,
              backgroundColor: isDarkTheme ? 'rgba(127, 29, 29, 0.18)' : '#fef2f2',
              color: isDarkTheme ? '#fecaca' : '#991b1b',
              fontSize: '12px',
              lineHeight: '1.5',
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: '8px' }}>JSON viewer diagnostic</div>
            <div><strong>Source:</strong> {viewerCrash.source}</div>
            <div><strong>Message:</strong> {viewerCrash.message}</div>
            {viewerCrash.stack && (
              <pre
                style={{
                  margin: '8px 0 0',
                  whiteSpace: 'pre-wrap',
                  fontFamily: 'var(--vscode-editor-font-family, monospace)',
                  fontSize: '11px',
                }}
              >
                {viewerCrash.stack}
              </pre>
            )}
            {viewerCrash.componentStack && (
              <pre
                style={{
                  margin: '8px 0 0',
                  whiteSpace: 'pre-wrap',
                  fontFamily: 'var(--vscode-editor-font-family, monospace)',
                  fontSize: '11px',
                }}
              >
                {viewerCrash.componentStack}
              </pre>
            )}
          </div>
        )}
        {parsedData !== null ? (
          <ViewerErrorBoundary
            isDarkTheme={isDarkTheme}
            onCrash={(details) => {
              console.error('[NodeEditModal] react crash', details);
              setViewerCrash(details);
            }}
          >
            <JSONViewer data={parsedData} isDarkTheme={isDarkTheme} onChange={handleJSONChange} />
          </ViewerErrorBoundary>
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
