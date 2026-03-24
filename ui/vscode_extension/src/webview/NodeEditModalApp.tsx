import React, { useState, useEffect, useRef } from 'react';
import { useIsVsCodeDarkTheme } from '@sovara/shared-components/utils/themeUtils';

declare global {
  interface Window {
    vscode?: {
      postMessage: (message: any) => void;
    };
    isNodeEditDialog?: boolean;
  }
}

interface NodeEditContext {
  nodeId: string;
  field: string;
  session_id?: string;
  attachments?: any;
}

export const NodeEditModalApp: React.FC = () => {
  const [title, setTitle] = useState<string>('');
  const [currentValue, setCurrentValue] = useState<string>('');
  const [originalValue, setOriginalValue] = useState<string>('');
  const [context, setContext] = useState<NodeEditContext | null>(null);
  const isDarkTheme = useIsVsCodeDarkTheme();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Calculate if data has changed
  const hasChanges = originalValue !== currentValue;

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const message = event.data;
      console.log('[NodeEditModalApp] Received message:', message.type, message);

      switch (message.type) {
        case 'init':
          setTitle(message.payload.title);
          setCurrentValue(message.payload.value);
          setOriginalValue(message.payload.originalValue);
          setContext(message.payload.context);
          // Focus the textarea after a brief delay
          setTimeout(() => {
            if (textareaRef.current) {
              textareaRef.current.focus();
              textareaRef.current.select();
            }
          }, 100);
          break;
        case 'updateContent':
          setTitle(message.payload.title);
          setCurrentValue(message.payload.value);
          setOriginalValue(message.payload.value);
          setContext(message.payload.context);
          break;
        case 'vscode-theme-change':
          // Theme changes are handled by the useIsVsCodeDarkTheme hook
          break;
      }
    };

    // Keyboard shortcuts
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        handleClose();
      } else if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        handleSave();
      }
    };

    window.addEventListener('message', handleMessage);
    window.addEventListener('keydown', handleKeyDown);
    
    // Send ready message
    if (window.vscode) {
      window.vscode.postMessage({ type: 'ready' });
    }

    return () => {
      window.removeEventListener('message', handleMessage);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  const handleSave = () => {
    if (window.vscode) {
      window.vscode.postMessage({
        type: 'save',
        payload: {
          value: currentValue
        }
      });
    }
  };

  const handleClose = () => {
    if (window.vscode) {
      window.vscode.postMessage({ type: 'close' });
    }
  };

  if (!context) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100vh',
          color: 'var(--vscode-editor-foreground)',
          background: 'var(--vscode-editor-background)',
        }}
      >
        Loading...
      </div>
    );
  }

  return (
    <div
      style={{
        margin: 0,
        padding: '16px',
        fontFamily: 'var(--vscode-font-family)',
        fontSize: 'var(--vscode-font-size)',
        color: 'var(--vscode-foreground)',
        background: 'var(--vscode-editor-background)',
        height: '100vh',
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Header */}
      <div
        style={{
          marginBottom: '16px',
          paddingBottom: '12px',
          borderBottom: '1px solid var(--vscode-editorWidget-border)',
        }}
      >
        <h2
          style={{
            margin: 0,
            fontSize: '14px',
            fontWeight: '600',
            color: 'var(--vscode-editor-foreground)',
          }}
        >
          {title}
        </h2>
      </div>

      {/* Content Area */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
        }}
      >
        <textarea
          ref={textareaRef}
          value={currentValue}
          onChange={(e) => setCurrentValue(e.target.value)}
          style={{
            flex: 1,
            padding: '12px',
            border: '1px solid var(--vscode-input-border)',
            borderRadius: '3px',
            background: 'var(--vscode-input-background)',
            color: 'var(--vscode-input-foreground)',
            fontFamily: 'var(--vscode-editor-font-family, var(--vscode-font-family))',
            fontSize: 'var(--vscode-editor-font-size, var(--vscode-font-size))',
            resize: 'none',
            outline: 'none',
            lineHeight: '1.4',
            minHeight: '200px',
          }}
          onFocus={(e) => {
            e.target.style.outline = '1px solid var(--vscode-focusBorder)';
            e.target.style.borderColor = 'var(--vscode-focusBorder)';
          }}
          onBlur={(e) => {
            e.target.style.outline = 'none';
            e.target.style.borderColor = 'var(--vscode-input-border)';
          }}
          placeholder={`Enter ${context.field} content...`}
        />
      </div>

      {/* Button Group */}
      <div
        style={{
          display: 'flex',
          gap: '12px',
          justifyContent: 'flex-end',
          marginTop: '16px',
          paddingTop: '12px',
          borderTop: '1px solid var(--vscode-editorWidget-border)',
        }}
      >
        <button
          onClick={handleClose}
          style={{
            padding: '8px 16px',
            border: '1px solid var(--vscode-button-border)',
            borderRadius: '3px',
            cursor: 'pointer',
            fontSize: '12px',
            fontFamily: 'var(--vscode-font-family)',
            background: 'var(--vscode-button-secondaryBackground)',
            color: 'var(--vscode-button-secondaryForeground)',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'var(--vscode-button-secondaryHoverBackground)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'var(--vscode-button-secondaryBackground)';
          }}
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          style={{
            padding: '8px 16px',
            border: '1px solid var(--vscode-button-border)',
            borderRadius: '3px',
            cursor: 'pointer',
            fontSize: '12px',
            fontFamily: 'var(--vscode-font-family)',
            background: 'var(--vscode-button-background)',
            color: 'var(--vscode-button-foreground)',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'var(--vscode-button-hoverBackground)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'var(--vscode-button-background)';
          }}
        >
          Save {navigator.platform.toLowerCase().includes('mac') ? '(⌘S)' : '(Ctrl+S)'}
        </button>
      </div>

      {/* Keyboard Hints */}
      <div
        style={{
          fontSize: '11px',
          color: 'var(--vscode-descriptionForeground)',
          marginTop: '8px',
          textAlign: 'center',
        }}
      >
        Press ESC to cancel • {navigator.platform.toLowerCase().includes('mac') ? '⌘S' : 'Ctrl+S'} to save
      </div>
    </div>
  );
};