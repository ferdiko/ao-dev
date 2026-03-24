import React, { useState, useEffect, useCallback } from 'react';
import { useIsVsCodeDarkTheme } from '@sovara/shared-components/utils/themeUtils';
import { LessonHeader } from '@sovara/shared-components/components/LessonHeader';
import { LessonSummary } from '@sovara/shared-components/types';

declare global {
  interface Window {
    vscode?: {
      postMessage: (message: any) => void;
    };
    lessonEditorContext?: {
      lessonId: string;
      lessonName: string;
    };
  }
}

interface LessonData {
  id: string;
  name: string;
  summary: string;
  content: string;
}

export const LessonEditorTabApp: React.FC = () => {
  const isDarkTheme = useIsVsCodeDarkTheme();
  const [context, setContext] = useState(window.lessonEditorContext || null);
  const [lesson, setLesson] = useState<LessonData | null>(null);
  const [lessons, setLessons] = useState<LessonSummary[]>([]);
  const [editedContent, setEditedContent] = useState('');
  const [editedName, setEditedName] = useState('');
  const [editedSummary, setEditedSummary] = useState('');
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [validationError, setValidationError] = useState<string | null>(null);
  const isNewLesson = context?.lessonId === 'new';
  // Track pending lesson fetch to update UI when response arrives
  const [pendingLessonId, setPendingLessonId] = useState<string | null>(null);

  // Request all lessons for dropdown via server proxy
  const requestAllLessons = useCallback(() => {
    if (window.vscode) {
      window.vscode.postMessage({ type: 'get_lessons' });
    }
  }, []);

  // Request single lesson data via server proxy
  const requestLesson = useCallback((lessonId: string) => {
    setLoading(true);
    setError(null);
    setPendingLessonId(lessonId);
    if (window.vscode) {
      window.vscode.postMessage({ type: 'get_lesson', lesson_id: lessonId });
    }
  }, []);

  // Load lesson on mount or when context changes
  useEffect(() => {
    if (context?.lessonId === 'new') {
      // New lesson - start with empty fields
      setLesson({ id: 'new', name: '', summary: '', content: '' });
      setEditedName('');
      setEditedSummary('');
      setEditedContent('');
      setHasUnsavedChanges(true); // Mark as unsaved since it's a new lesson
      setLoading(false);
    } else if (context?.lessonId) {
      requestLesson(context.lessonId);
    }
  }, [context, requestLesson]);

  // Request all lessons on mount
  useEffect(() => {
    requestAllLessons();
  }, [requestAllLessons]);

  // Listen for messages from extension
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const message = event.data;

      switch (message.type) {
        case 'updateLessonData':
          setContext(message.payload);
          break;

        case 'lessons_list':
          // Response to get_lessons - update dropdown
          setLessons(message.lessons || []);
          break;

        case 'lesson_content':
          // Response to get_lesson - populate editor
          if (message.lesson && message.lesson.id === pendingLessonId) {
            const data = message.lesson;
            setLesson(data);
            setEditedContent(data.content || '');
            setEditedName(data.name || '');
            setEditedSummary(data.summary || '');
            setHasUnsavedChanges(false);
            setLoading(false);
            setPendingLessonId(null);
          }
          break;

        case 'lesson_created':
        case 'lesson_updated':
          // Success - update lesson and show saved status
          if (message.lesson) {
            const updatedLesson = message.lesson;
            setLesson(updatedLesson);
            // Update context with new lesson ID if it was a new lesson
            if (isNewLesson && updatedLesson.id) {
              setContext({ lessonId: updatedLesson.id, lessonName: updatedLesson.name });
            }
            setHasUnsavedChanges(false);
            setSaveStatus('saved');
            // Refresh lessons list for dropdown
            requestAllLessons();
            setTimeout(() => setSaveStatus('idle'), 2000);
          }
          break;

        case 'lesson_rejected':
          // Validation rejected - show error
          setValidationError(message.reason || 'Validation failed');
          setSaveStatus('error');
          setTimeout(() => {
            setSaveStatus('idle');
            setValidationError(null);
          }, 5000);
          break;

        case 'lesson_error':
          // General error
          if (pendingLessonId) {
            setError(message.error || 'Failed to load lesson');
            setLoading(false);
            setPendingLessonId(null);
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
  }, [pendingLessonId, isNewLesson, requestAllLessons]);

  // Detect changes
  useEffect(() => {
    if (!lesson) return;
    // For new lessons, always mark as unsaved (they need to be created)
    if (lesson.id === 'new') {
      setHasUnsavedChanges(true);
      return;
    }
    const contentChanged = editedContent !== (lesson.content || '');
    const nameChanged = editedName !== (lesson.name || '');
    const summaryChanged = editedSummary !== (lesson.summary || '');
    setHasUnsavedChanges(contentChanged || nameChanged || summaryChanged);
  }, [editedContent, editedName, editedSummary, lesson]);

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

    if (isNewLesson) {
      // Create new lesson via server proxy
      window.vscode.postMessage({
        type: 'add_lesson',
        name: editedName.trim(),
        summary: editedSummary.trim(),
        content: editedContent.trim(),
      });
    } else {
      // Update existing lesson via server proxy
      window.vscode.postMessage({
        type: 'update_lesson',
        lesson_id: context?.lessonId,
        name: editedName.trim(),
        summary: editedSummary.trim(),
        content: editedContent.trim(),
      });
    }

    // Notify sidebar to refresh when save completes (handled in message listener)
    if (window.vscode) {
      window.vscode.postMessage({ type: 'lessonUpdated' });
    }
  }, [context?.lessonId, editedContent, editedName, editedSummary, isNewLesson, validateFields]);

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

  // Handle navigating to a different lesson
  const handleNavigateToLesson = useCallback((lessonSummary: LessonSummary) => {
    setContext({ lessonId: lessonSummary.id, lessonName: lessonSummary.name });
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
        Loading lesson...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ ...containerStyle, alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ color: '#e05252' }}>{error}</div>
        <button
          style={{ ...buttonStyle, marginTop: '16px' }}
          onClick={() => context?.lessonId && requestLesson(context.lessonId)}
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div style={containerStyle}>
      {/* Header with dropdown and action icons */}
      <LessonHeader
        lessonName={editedName || lesson?.name || (isNewLesson ? 'New Lesson' : 'Lesson')}
        lessonId={context?.lessonId || ''}
        isDarkTheme={isDarkTheme}
        lessons={lessons}
        hasUnsavedChanges={canSave()}
        showPreview={showPreview}
        saveStatus={saveStatus}
        onNavigateToLesson={handleNavigateToLesson}
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
          placeholder="Lesson name"
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
            placeholder="Write your lesson content in markdown..."
          />
        )}
      </div>
    </div>
  );
};
