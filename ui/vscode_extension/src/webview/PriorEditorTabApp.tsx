import React, { useState, useEffect, useCallback } from 'react';
import { useIsVsCodeDarkTheme } from '@sovara/shared-components/utils/themeUtils';
import { PriorHeader } from '@sovara/shared-components/components/PriorHeader';
import { PriorSummary } from '@sovara/shared-components/types';

declare global {
  interface Window {
    vscode?: {
      postMessage: (message: any) => void;
    };
    priorEditorContext?: {
      priorId: string;
      priorName: string;
    };
  }
}

interface PriorData {
  id: string;
  name: string;
  summary: string;
  content: string;
}

export const PriorEditorTabApp: React.FC = () => {
  const isDarkTheme = useIsVsCodeDarkTheme();
  const [context, setContext] = useState(window.priorEditorContext || null);
  const [prior, setPrior] = useState<PriorData | null>(null);
  const [priors, setPriors] = useState<PriorSummary[]>([]);
  const [editedContent, setEditedContent] = useState('');
  const [editedName, setEditedName] = useState('');
  const [editedSummary, setEditedSummary] = useState('');
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [validationError, setValidationError] = useState<string | null>(null);
  const isNewPrior = context?.priorId === 'new';
  // Track pending prior fetch to update UI when response arrives
  const [pendingPriorId, setPendingPriorId] = useState<string | null>(null);

  // Request all priors for dropdown via server proxy
  const requestAllPriors = useCallback(() => {
    if (window.vscode) {
      window.vscode.postMessage({ type: 'get_priors' });
    }
  }, []);

  // Request single prior data via server proxy
  const requestPrior = useCallback((priorId: string) => {
    setLoading(true);
    setError(null);
    setPendingPriorId(priorId);
    if (window.vscode) {
      window.vscode.postMessage({ type: 'get_prior', prior_id: priorId });
    }
  }, []);

  // Load prior on mount or when context changes
  useEffect(() => {
    if (context?.priorId === 'new') {
      // New prior - start with empty fields
      setPrior({ id: 'new', name: '', summary: '', content: '' });
      setEditedName('');
      setEditedSummary('');
      setEditedContent('');
      setHasUnsavedChanges(true); // Mark as unsaved since it's a new prior
      setLoading(false);
    } else if (context?.priorId) {
      requestPrior(context.priorId);
    }
  }, [context, requestPrior]);

  // Request all priors on mount
  useEffect(() => {
    requestAllPriors();
  }, [requestAllPriors]);

  // Listen for messages from extension
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const message = event.data;

      switch (message.type) {
        case 'updatePriorData':
          setContext(message.payload);
          break;

        case 'priors_list':
          // Response to get_priors - update dropdown
          setPriors(message.priors || []);
          break;

        case 'prior_content':
          // Response to get_prior - populate editor
          if (message.prior && message.prior.id === pendingPriorId) {
            const data = message.prior;
            setPrior(data);
            setEditedContent(data.content || '');
            setEditedName(data.name || '');
            setEditedSummary(data.summary || '');
            setHasUnsavedChanges(false);
            setLoading(false);
            setPendingPriorId(null);
          }
          break;

        case 'prior_created':
        case 'prior_updated':
          // Success - update prior and show saved status
          if (message.prior) {
            const updatedPrior = message.prior;
            setPrior(updatedPrior);
            // Update context with new prior ID if it was a new prior
            if (isNewPrior && updatedPrior.id) {
              setContext({ priorId: updatedPrior.id, priorName: updatedPrior.name });
            }
            setHasUnsavedChanges(false);
            setSaveStatus('saved');
            // Refresh priors list for dropdown
            requestAllPriors();
            setTimeout(() => setSaveStatus('idle'), 2000);
          }
          break;

        case 'prior_rejected':
          // Validation rejected - show error
          setValidationError(message.reason || 'Validation failed');
          setSaveStatus('error');
          setTimeout(() => {
            setSaveStatus('idle');
            setValidationError(null);
          }, 5000);
          break;

        case 'prior_error':
          // General error
          if (pendingPriorId) {
            setError(message.error || 'Failed to load prior');
            setLoading(false);
            setPendingPriorId(null);
          } else {
            setValidationError(message.error || 'Server error');
            setSaveStatus('error');
            setTimeout(() => {
              setSaveStatus('idle');
              setValidationError(null);
            }, 3000);
          }
          break;
      }
    };

    window.addEventListener('message', handleMessage);

    if (window.vscode) {
      window.vscode.postMessage({ type: 'ready' });
    }

    return () => {
      window.removeEventListener('message', handleMessage);
    };
  }, [pendingPriorId, isNewPrior, requestAllPriors]);

  // Detect changes
  useEffect(() => {
    if (!prior) return;
    // For new priors, always mark as unsaved (they need to be created)
    if (prior.id === 'new') {
      setHasUnsavedChanges(true);
      return;
    }
    const contentChanged = editedContent !== (prior.content || '');
    const nameChanged = editedName !== (prior.name || '');
    const summaryChanged = editedSummary !== (prior.summary || '');
    setHasUnsavedChanges(contentChanged || nameChanged || summaryChanged);
  }, [editedContent, editedName, editedSummary, prior]);

  // Validate fields
  const validateFields = useCallback((): string | null => {
    if (!editedName.trim()) return 'Name is required';
    if (!editedSummary.trim()) return 'Summary is required';
    if (!editedContent.trim()) return 'Content is required';
    return null;
  }, [editedName, editedSummary, editedContent]);

  // Check if save is allowed
  const canSave = useCallback(() => {
    return hasUnsavedChanges && !validateFields();
  }, [hasUnsavedChanges, validateFields]);

  // Handle save via server proxy
  const handleSave = useCallback(() => {
    // Validate fields
    const validationErr = validateFields();
    if (validationErr) {
      setValidationError(validationErr);
      setTimeout(() => setValidationError(null), 3000);
      return;
    }

    setSaveStatus('saving');
    setValidationError(null);

    if (!window.vscode) {
      setValidationError('VSCode API not available');
      setSaveStatus('error');
      return;
    }

    if (isNewPrior) {
      // Create new prior via server proxy
      window.vscode.postMessage({
        type: 'add_prior',
        name: editedName.trim(),
        summary: editedSummary.trim(),
        content: editedContent.trim(),
      });
    } else {
      // Update existing prior via server proxy
      window.vscode.postMessage({
        type: 'update_prior',
        prior_id: context?.priorId,
        name: editedName.trim(),
        summary: editedSummary.trim(),
        content: editedContent.trim(),
      });
    }
  }, [context?.priorId, editedContent, editedName, editedSummary, isNewPrior, validateFields]);

  // Handle CMD+S / Ctrl+S keyboard shortcut for save
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 's') {
        event.preventDefault();
        handleSave();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [handleSave]);

  // Handle navigating to a different prior
  const handleNavigateToPrior = useCallback((priorSummary: PriorSummary) => {
    setContext({ priorId: priorSummary.id, priorName: priorSummary.name });
    setShowPreview(false);
  }, []);

  // Simple markdown to HTML conversion for preview
  const renderMarkdown = (text: string): string => {
    return text
      .replace(/^### (.*$)/gm, '<h3>$1</h3>')
      .replace(/^## (.*$)/gm, '<h2>$1</h2>')
      .replace(/^# (.*$)/gm, '<h1>$1</h1>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
      .replace(/\n/g, '<br/>');
  };

  const containerStyle: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    backgroundColor: isDarkTheme ? '#1e1e1e' : '#ffffff',
    color: isDarkTheme ? '#cccccc' : '#333333',
    fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
  };

  const inputStyle: React.CSSProperties = {
    flex: 1,
    padding: '6px 10px',
    fontSize: '14px',
    backgroundColor: isDarkTheme ? '#3c3c3c' : '#ffffff',
    color: isDarkTheme ? '#cccccc' : '#333333',
    border: `1px solid ${isDarkTheme ? '#555555' : '#cccccc'}`,
    borderRadius: '4px',
    marginRight: '12px',
  };

  const buttonStyle: React.CSSProperties = {
    padding: '6px 16px',
    fontSize: '13px',
    backgroundColor: isDarkTheme ? '#0e639c' : '#007acc',
    color: '#ffffff',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    marginLeft: '8px',
  };

  const editorStyle: React.CSSProperties = {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  };

  const textareaStyle: React.CSSProperties = {
    flex: 1,
    padding: '16px',
    fontSize: '14px',
    lineHeight: '1.6',
    backgroundColor: isDarkTheme ? '#1e1e1e' : '#ffffff',
    color: isDarkTheme ? '#cccccc' : '#333333',
    border: 'none',
    resize: 'none',
    fontFamily: 'monospace',
    outline: 'none',
  };

  const previewStyle: React.CSSProperties = {
    flex: 1,
    padding: '16px',
    overflow: 'auto',
    backgroundColor: isDarkTheme ? '#252525' : '#f5f5f5',
  };

  const fieldRowStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    padding: '8px 16px',
    borderBottom: `1px solid ${isDarkTheme ? '#3c3c3c' : '#e0e0e0'}`,
  };

  const labelStyle: React.CSSProperties = {
    width: '80px',
    fontSize: '12px',
    fontWeight: 600,
    color: isDarkTheme ? '#888888' : '#666666',
  };

  if (loading) {
    return (
      <div style={{ ...containerStyle, alignItems: 'center', justifyContent: 'center' }}>
        Loading prior...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ ...containerStyle, alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ color: '#e05252' }}>{error}</div>
        <button
          style={{ ...buttonStyle, marginTop: '16px' }}
          onClick={() => context?.priorId && requestPrior(context.priorId)}
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div style={containerStyle}>
      {/* Header with dropdown and action icons */}
      <PriorHeader
        priorName={editedName || prior?.name || (isNewPrior ? 'New Prior' : 'Prior')}
        priorId={context?.priorId || ''}
        isDarkTheme={isDarkTheme}
        priors={priors}
        hasUnsavedChanges={canSave()}
        showPreview={showPreview}
        saveStatus={saveStatus}
        onNavigateToPrior={handleNavigateToPrior}
        onTogglePreview={() => setShowPreview(!showPreview)}
        onSave={handleSave}
      />

      {/* Validation error banner */}
      {validationError && (
        <div style={{
          padding: '8px 16px',
          backgroundColor: isDarkTheme ? '#5a1d1d' : '#fde7e7',
          color: isDarkTheme ? '#f48771' : '#c53030',
          fontSize: '12px',
          borderBottom: `1px solid ${isDarkTheme ? '#742a2a' : '#feb2b2'}`,
        }}>
          {validationError}
        </div>
      )}

      {/* Name field */}
      <div style={fieldRowStyle}>
        <span style={labelStyle}>Name</span>
        <input
          type="text"
          value={editedName}
          onChange={(e) => setEditedName(e.target.value)}
          style={inputStyle}
          placeholder="Prior name"
        />
      </div>

      {/* Summary field */}
      <div style={fieldRowStyle}>
        <span style={labelStyle}>Summary</span>
        <input
          type="text"
          value={editedSummary}
          onChange={(e) => setEditedSummary(e.target.value)}
          style={inputStyle}
          placeholder="Brief summary"
        />
      </div>

      {/* Editor/Preview */}
      <div style={editorStyle}>
        {showPreview ? (
          <div
            style={previewStyle}
            dangerouslySetInnerHTML={{ __html: renderMarkdown(editedContent) }}
          />
        ) : (
          <textarea
            style={textareaStyle}
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            placeholder="Write your prior content in markdown..."
          />
        )}
      </div>
    </div>
  );
};
