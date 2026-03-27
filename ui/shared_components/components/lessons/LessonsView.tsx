import React, { useState, useEffect, useRef, useCallback } from 'react';

export interface Lesson {
  id: string;
  name: string;
  summary: string;
  content: string;
  path?: string;
  appliedTo?: { runId: string; nodeId?: string; runName: string }[];
  extractedFrom?: { runId: string; nodeId?: string };
  validationSeverity?: 'info' | 'warning' | 'error';
}

export interface LessonFormData {
  name: string;
  summary: string;
  content: string;
  path?: string;
}

export interface ValidationResult {
  feedback: string;
  severity: 'info' | 'warning' | 'error';
  conflicting_lesson_ids: string[];
  isRejected?: boolean;
}

export interface FolderEntry {
  path: string;
  lesson_count: number;
}

export interface FolderData {
  folders: FolderEntry[];
  lessons: Lesson[];
  lessonCount?: number;
}

interface LessonsViewProps {
  isDarkTheme: boolean;
  onLessonCreate?: (data: LessonFormData, force?: boolean) => void;
  onLessonUpdate?: (id: string, data: Partial<LessonFormData>, force?: boolean) => void;
  onLessonDelete?: (id: string) => void;
  onNavigateToRun?: (runId: string, nodeId?: string) => void;
  onFetchLessonContent?: (id: string) => void;
  onFetchFolder?: (path: string) => void;
  validationResult?: ValidationResult | null;
  isValidating?: boolean;
  onClearValidation?: () => void;
  apiKeyError?: boolean;
  /** Incoming folder data from server — the parent sets this when folder_ls_result arrives */
  folderResult?: { path: string; folders: FolderEntry[]; lessons: Lesson[]; lessonCount?: number } | null;
  /** Incoming lesson content update */
  lessonContentUpdate?: { id: string; content: string } | null;
  /** Fetch runs a lesson was applied to (lazy, per-lesson). Returns a Promise so each result is handled independently. */
  onFetchAppliedRuns?: (lessonId: string) => Promise<{ runId: string; nodeId?: string; runName: string }[]>;
}

// Loading spinner component
const Spinner: React.FC<{ isDark: boolean }> = ({ isDark }) => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    style={{
      animation: 'spin 1s linear infinite',
      marginLeft: '8px',
    }}
  >
    <style>{`@keyframes spin { 100% { transform: rotate(360deg); } }`}</style>
    <circle
      cx="8"
      cy="8"
      r="6"
      fill="none"
      stroke={isDark ? '#888888' : '#666666'}
      strokeWidth="2"
      strokeDasharray="24"
      strokeDashoffset="8"
      strokeLinecap="round"
    />
  </svg>
);

// Get border color based on severity
const getSeverityColor = (severity: string | undefined, isDark: boolean): string => {
  switch (severity) {
    case 'info': return isDark ? '#3a7644' : '#43884e';
    case 'warning': return isDark ? '#c9a227' : '#f0ad4e';
    case 'error': return isDark ? '#b33b3b' : '#d9534f';
    default: return isDark ? '#3c3c3c' : '#d0d0d0';
  }
};

export const LessonsView: React.FC<LessonsViewProps> = ({
  isDarkTheme,
  onLessonCreate,
  onLessonUpdate,
  onLessonDelete,
  onNavigateToRun,
  onFetchLessonContent,
  onFetchFolder,
  validationResult,
  isValidating,
  onClearValidation,
  apiKeyError,
  folderResult,
  lessonContentUpdate,
  onFetchAppliedRuns,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<LessonFormData>({ name: '', summary: '', content: '', path: '' });
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createForm, setCreateForm] = useState<LessonFormData>({ name: '', summary: '', content: '', path: '' });
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [expandedAppliedIds, setExpandedAppliedIds] = useState<Set<string>>(new Set());
  const [loadingContentIds, setLoadingContentIds] = useState<Set<string>>(new Set());
  const lessonRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // Folder tree state
  const [folderData, setFolderData] = useState<Map<string, FolderData>>(new Map());
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [loadingFolders, setLoadingFolders] = useState<Set<string>>(new Set());

  // Fetch root folder on mount
  useEffect(() => {
    onFetchFolder?.('');
    setLoadingFolders(new Set(['']));
  }, []);

  // Process incoming folder results
  useEffect(() => {
    if (!folderResult) return;
    const { path, folders, lessons, lessonCount } = folderResult;
    setFolderData((prev) => {
      const next = new Map(prev);
      next.set(path, { folders, lessons, lessonCount });
      return next;
    });
    setLoadingFolders((prev) => {
      const next = new Set(prev);
      next.delete(path);
      return next;
    });
  }, [folderResult]);

  // Process incoming lesson content updates
  useEffect(() => {
    if (!lessonContentUpdate) return;
    const { id, content } = lessonContentUpdate;
    setLoadingContentIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
    // Update the lesson content in folderData
    setFolderData((prev) => {
      const next = new Map(prev);
      for (const [path, data] of next) {
        const idx = data.lessons.findIndex((l) => l.id === id);
        if (idx !== -1) {
          const updatedLessons = [...data.lessons];
          updatedLessons[idx] = { ...updatedLessons[idx], content };
          next.set(path, { ...data, lessons: updatedLessons });
          break;
        }
      }
      return next;
    });
  }, [lessonContentUpdate]);

  // Fetch applied-run counts when new lessons become visible
  const fetchedAppliedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!folderResult || !onFetchAppliedRuns) return;
    for (const lesson of folderResult.lessons) {
      if (!fetchedAppliedRef.current.has(lesson.id)) {
        fetchedAppliedRef.current.add(lesson.id);
        const lessonId = lesson.id;
        onFetchAppliedRuns(lessonId).then(runs => {
          setFolderData((prev) => {
            const next = new Map(prev);
            for (const [path, data] of next) {
              const idx = data.lessons.findIndex((l) => l.id === lessonId);
              if (idx !== -1) {
                const updatedLessons = [...data.lessons];
                updatedLessons[idx] = { ...updatedLessons[idx], appliedTo: runs };
                next.set(path, { ...data, lessons: updatedLessons });
                break;
              }
            }
            return next;
          });
        });
      }
    }
  }, [folderResult, onFetchAppliedRuns]);

  // Collect all loaded lessons for search
  const allLoadedLessons = useCallback((): Lesson[] => {
    const lessons: Lesson[] = [];
    for (const data of folderData.values()) {
      lessons.push(...data.lessons);
    }
    return lessons;
  }, [folderData]);

  // Check if a lesson matches the search query
  const lessonMatches = useCallback((lesson: Lesson, query: string): boolean => {
    if (!query) return false;
    const q = query.toLowerCase();
    if (lesson.name.toLowerCase().includes(q)) return true;
    if (lesson.summary.toLowerCase().includes(q)) return true;
    if (expandedIds.has(lesson.id) && lesson.content && lesson.content.toLowerCase().includes(q)) return true;
    return false;
  }, [expandedIds]);

  const matchingLessonIds = searchQuery
    ? allLoadedLessons().filter((lesson) => lessonMatches(lesson, searchQuery)).map((l) => l.id)
    : [];

  useEffect(() => {
    setCurrentMatchIndex(0);
  }, [searchQuery, matchingLessonIds.length]);

  useEffect(() => {
    if (matchingLessonIds.length > 0 && currentMatchIndex < matchingLessonIds.length) {
      const matchId = matchingLessonIds[currentMatchIndex];
      const element = lessonRefs.current.get(matchId);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }, [currentMatchIndex, matchingLessonIds]);

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && matchingLessonIds.length > 0) {
      e.preventDefault();
      setCurrentMatchIndex((prev) => (prev + 1) % matchingLessonIds.length);
    }
  };

  const highlightText = (text: string, isCurrentMatch: boolean): React.ReactNode => {
    if (!searchQuery || !text) return text;
    const query = searchQuery.toLowerCase();
    const lowerText = text.toLowerCase();
    const index = lowerText.indexOf(query);
    if (index === -1) return text;
    const before = text.slice(0, index);
    const match = text.slice(index, index + searchQuery.length);
    const after = text.slice(index + searchQuery.length);
    return (
      <>
        {before}
        <mark
          style={{
            backgroundColor: isCurrentMatch
              ? (isDarkTheme ? '#4a9eff' : '#ffeb3b')
              : (isDarkTheme ? '#5a5a00' : '#fff59d'),
            color: isCurrentMatch ? '#000' : (isDarkTheme ? '#fff' : '#000'),
            padding: '1px 2px',
            borderRadius: '2px',
          }}
        >
          {match}
        </mark>
        {highlightText(after, isCurrentMatch)}
      </>
    );
  };

  const handleStartEdit = (lesson: Lesson) => {
    setEditingId(lesson.id);
    setEditForm({
      name: lesson.name,
      summary: lesson.summary,
      content: lesson.content,
      path: lesson.path || '',
    });
    onClearValidation?.();
  };

  const handleSaveEdit = (id: string, force: boolean = false) => {
    if (onLessonUpdate) {
      onLessonUpdate(id, editForm, force);
      // If force save, close immediately. Otherwise wait for validation response.
      if (force) {
        setEditingId(null);
        setEditForm({ name: '', summary: '', content: '', path: '' });
      }
    }
  };

  const handleCancelEdit = () => {
    setEditingId(null);
    setEditForm({ name: '', summary: '', content: '', path: '' });
    onClearValidation?.();
  };

  const handleCreate = (force: boolean = false) => {
    if (onLessonCreate && createForm.name && createForm.content) {
      onLessonCreate(createForm, force);
      // If force save, close immediately. Otherwise wait for validation response.
      if (force) {
        setShowCreateModal(false);
        setCreateForm({ name: '', summary: '', content: '', path: '' });
      }
    }
  };

  // Close modal when validation succeeds (non-rejected response received)
  useEffect(() => {
    if (validationResult && !validationResult.isRejected && !isValidating) {
      // Validation passed - close modal after a short delay to show feedback
      const timer = setTimeout(() => {
        if (showCreateModal) {
          setShowCreateModal(false);
          setCreateForm({ name: '', summary: '', content: '', path: '' });
        }
        if (editingId) {
          setEditingId(null);
          setEditForm({ name: '', summary: '', content: '', path: '' });
        }
        onClearValidation?.();
      }, 1500); // 1.5s delay to let user see feedback
      return () => clearTimeout(timer);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [validationResult, isValidating, showCreateModal, editingId]);

  const handleCancelCreate = () => {
    setShowCreateModal(false);
    setCreateForm({ name: '', summary: '', content: '', path: '' });
    onClearValidation?.();
  };

  const toggleLessonExpanded = (id: string, lesson: Lesson) => {
    const isExpanding = !expandedIds.has(id);
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
    if (isExpanding && !lesson.content && onFetchLessonContent) {
      setLoadingContentIds((prev) => new Set(prev).add(id));
      onFetchLessonContent(id);
    }
  };

  const toggleFolder = (path: string) => {
    const isExpanding = !expandedFolders.has(path);
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
    // Lazy-load folder contents if not yet fetched
    if (isExpanding && !folderData.has(path)) {
      setLoadingFolders((prev) => new Set(prev).add(path));
      onFetchFolder?.(path);
    }
  };

  // Public method to refresh all expanded folders (called on lessons_refresh)
  // This is handled by the parent re-fetching folders — we expose expandedFolders via callback

  const buttonStyle = (isDark: boolean, variant: 'primary' | 'secondary' | 'danger' | 'warning' = 'secondary') => ({
    padding: '4px 10px',
    fontSize: '11px',
    fontWeight: 500 as const,
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    backgroundColor:
      variant === 'primary'
        ? isDark ? '#0e639c' : '#007acc'
        : variant === 'danger'
          ? isDark ? '#5a1d1d' : '#ffebee'
          : variant === 'warning'
            ? isDark ? '#8a6914' : '#f0ad4e'
            : isDark ? '#3c3c3c' : '#e8e8e8',
    color:
      variant === 'primary'
        ? '#ffffff'
        : variant === 'danger'
          ? isDark ? '#f48771' : '#d32f2f'
          : variant === 'warning'
            ? '#ffffff'
            : isDark ? '#cccccc' : '#333333',
    transition: 'background-color 0.15s ease',
  });

  const inputStyle = (isDark: boolean) => ({
    width: '100%',
    padding: '8px 10px',
    fontSize: '13px',
    border: `1px solid ${isDark ? '#3c3c3c' : '#d0d0d0'}`,
    borderRadius: '4px',
    backgroundColor: isDark ? '#2d2d2d' : '#ffffff',
    color: isDark ? '#e5e5e5' : '#333333',
    outline: 'none',
    boxSizing: 'border-box' as const,
    fontFamily: 'inherit',
  });

  const labelStyle = (isDark: boolean) => ({
    display: 'block',
    fontSize: '12px',
    fontWeight: 500 as const,
    marginBottom: '4px',
    color: isDark ? '#cccccc' : '#555555',
  });

  // Handle Escape key to close modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (showCreateModal) {
          handleCancelCreate();
        } else if (editingId) {
          handleCancelEdit();
        }
      }
    };
    if (showCreateModal || editingId) {
      window.addEventListener('keydown', handleKeyDown);
      return () => window.removeEventListener('keydown', handleKeyDown);
    }
  }, [showCreateModal, editingId]);

  // Modal component for create/edit with validation feedback panel
  const renderModal = (
    title: string,
    form: LessonFormData,
    setForm: React.Dispatch<React.SetStateAction<LessonFormData>>,
    onSave: (force?: boolean) => void,
    onCancel: () => void
  ) => (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        style={{
          backgroundColor: isDarkTheme ? '#252525' : '#ffffff',
          borderRadius: '8px',
          padding: '24px',
          width: '800px',
          maxWidth: '95vw',
          maxHeight: '85vh',
          overflow: 'auto',
          boxShadow: '0 4px 20px rgba(0, 0, 0, 0.3)',
          position: 'relative',
        }}
      >
        {/* Close button (X) in top right */}
        <button
          onClick={onCancel}
          style={{
            position: 'absolute',
            top: '12px',
            right: '12px',
            background: 'transparent',
            border: 'none',
            fontSize: '20px',
            lineHeight: 1,
            color: isDarkTheme ? '#888888' : '#666666',
            cursor: 'pointer',
            padding: '4px 8px',
            borderRadius: '4px',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = isDarkTheme ? '#3c3c3c' : '#e8e8e8';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'transparent';
          }}
          title="Close (Esc)"
        >
          ×
        </button>

        {/* Header with title and spinner */}
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: '20px' }}>
          <h3 style={{ margin: 0, fontSize: '16px', color: isDarkTheme ? '#e5e5e5' : '#333333' }}>
            {title}
          </h3>
          {isValidating && <Spinner isDark={isDarkTheme} />}
        </div>

        {/* Two-column layout */}
        <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
          {/* Left column: Form fields */}
          <div style={{ flex: '1 1 300px', minWidth: '280px' }}>
            <div style={{ marginBottom: '16px' }}>
              <label style={labelStyle(isDarkTheme)}>Name *</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                style={inputStyle(isDarkTheme)}
                placeholder="Lesson title"
                maxLength={200}
                disabled={isValidating}
              />
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={labelStyle(isDarkTheme)}>Summary *</label>
              <textarea
                value={form.summary}
                onChange={(e) => setForm({ ...form, summary: e.target.value })}
                style={{ ...inputStyle(isDarkTheme), minHeight: '60px', resize: 'vertical' }}
                placeholder="Brief description"
                maxLength={1000}
                disabled={isValidating}
              />
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={labelStyle(isDarkTheme)}>Content *</label>
              <textarea
                value={form.content}
                onChange={(e) => setForm({ ...form, content: e.target.value })}
                style={{ ...inputStyle(isDarkTheme), minHeight: '120px', resize: 'vertical' }}
                placeholder="Full lesson content (markdown supported)"
                disabled={isValidating}
              />
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={labelStyle(isDarkTheme)}>Path (optional)</label>
              <input
                type="text"
                value={form.path || ''}
                onChange={(e) => setForm({ ...form, path: e.target.value })}
                style={inputStyle(isDarkTheme)}
                placeholder="e.g., beaver/retriever/"
                disabled={isValidating}
              />
            </div>
          </div>

          {/* Right column: Validation feedback */}
          <div style={{ flex: '1 1 250px', minWidth: '220px' }}>
            <label style={labelStyle(isDarkTheme)}>AI Validation Feedback</label>
            <div
              style={{
                padding: '12px',
                minHeight: '200px',
                maxHeight: '350px',
                overflow: 'auto',
                backgroundColor: isDarkTheme ? '#1e1e1e' : '#f8f8f8',
                border: `2px solid ${getSeverityColor(validationResult?.severity, isDarkTheme)}`,
                borderRadius: '4px',
                fontSize: '12px',
                lineHeight: '1.5',
                color: isDarkTheme ? '#d4d4d4' : '#444444',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {isValidating ? (
                <span style={{ color: isDarkTheme ? '#888888' : '#666666', fontStyle: 'italic' }}>
                  Validating lesson with AI...
                </span>
              ) : validationResult?.feedback ? (
                validationResult.feedback
              ) : (
                <span style={{ color: isDarkTheme ? '#888888' : '#666666', fontStyle: 'italic' }}>
                  Click Save to validate the lesson. Feedback from the AI validator will appear here.
                </span>
              )}
            </div>

            {/* Severity indicator */}
            {validationResult && !isValidating && (
              <div style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span
                  style={{
                    width: '10px',
                    height: '10px',
                    borderRadius: '50%',
                    backgroundColor: getSeverityColor(validationResult.severity, isDarkTheme),
                  }}
                />
                <span style={{ fontSize: '11px', color: isDarkTheme ? '#cccccc' : '#555555', textTransform: 'capitalize' }}>
                  {validationResult.isRejected ? 'Rejected' : validationResult.severity}
                </span>
                {validationResult.conflicting_lesson_ids.length > 0 && (
                  <span style={{ fontSize: '11px', color: isDarkTheme ? '#888888' : '#666666' }}>
                    ({validationResult.conflicting_lesson_ids.length} conflicts)
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Button row */}
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', marginTop: '20px' }}>
          <button
            onClick={onCancel}
            style={buttonStyle(isDarkTheme)}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = isDarkTheme ? '#4a4a4a' : '#d0d0d0';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = isDarkTheme ? '#3c3c3c' : '#e8e8e8';
            }}
          >
            Cancel
          </button>

          {/* Force Save button - only show when validation rejected */}
          {validationResult?.isRejected && (
            <button
              onClick={() => onSave(true)}
              style={buttonStyle(isDarkTheme, 'warning')}
              disabled={isValidating || !form.name || !form.summary || !form.content}
              onMouseEnter={(e) => {
                if (!isValidating && form.name && form.summary && form.content) {
                  e.currentTarget.style.backgroundColor = isDarkTheme ? '#a07a18' : '#ec971f';
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = isDarkTheme ? '#8a6914' : '#f0ad4e';
              }}
            >
              Force Save
            </button>
          )}

          <button
            onClick={() => onSave(false)}
            style={{
              ...buttonStyle(isDarkTheme, 'primary'),
              opacity: isValidating || !form.name || !form.summary || !form.content ? 0.6 : 1,
            }}
            disabled={isValidating || !form.name || !form.summary || !form.content}
            onMouseEnter={(e) => {
              if (!isValidating && form.name && form.summary && form.content) {
                e.currentTarget.style.backgroundColor = isDarkTheme ? '#1177bb' : '#0062a3';
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = isDarkTheme ? '#0e639c' : '#007acc';
            }}
          >
            {isValidating ? 'Validating...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );

  // Render a single lesson card
  const renderLessonCard = (lesson: Lesson) => {
    const isCurrentMatch = !!(searchQuery && matchingLessonIds[currentMatchIndex] === lesson.id);
    return (
      <div
        key={lesson.id}
        ref={(el) => {
          if (el) lessonRefs.current.set(lesson.id, el);
          else lessonRefs.current.delete(lesson.id);
        }}
        style={{
          backgroundColor: isDarkTheme ? '#2d2d2d' : '#fafafa',
          border: `1px solid ${isDarkTheme ? '#3c3c3c' : '#e0e0e0'}`,
          borderLeft: lesson.validationSeverity
            ? `3px solid ${getSeverityColor(lesson.validationSeverity, isDarkTheme)}`
            : `1px solid ${isDarkTheme ? '#3c3c3c' : '#e0e0e0'}`,
          borderRadius: '6px',
          padding: '14px 16px',
        }}
      >
        {/* Header: Name and Path */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '6px' }}>
          <h4
            style={{
              margin: 0,
              fontSize: '14px',
              fontWeight: 600,
              color: isDarkTheme ? '#e5e5e5' : '#333333',
            }}
          >
            {highlightText(lesson.name, isCurrentMatch)}
          </h4>
          {lesson.path && (
            <span
              style={{
                fontSize: '10px',
                padding: '2px 6px',
                borderRadius: '3px',
                backgroundColor: isDarkTheme ? '#3c3c3c' : '#e0e0e0',
                color: isDarkTheme ? '#999999' : '#666666',
                marginLeft: '8px',
                flexShrink: 0,
              }}
            >
              {lesson.path}
            </span>
          )}
        </div>

        {/* Summary */}
        <p
          style={{
            margin: '0 0 10px 0',
            fontSize: '12px',
            lineHeight: '1.5',
            color: isDarkTheme ? '#999999' : '#666666',
          }}
        >
          {highlightText(lesson.summary, isCurrentMatch)}
        </p>

        {/* Action Buttons */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          {onLessonUpdate && (
            <button
              onClick={() => handleStartEdit(lesson)}
              style={buttonStyle(isDarkTheme)}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = isDarkTheme ? '#4a4a4a' : '#d0d0d0';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = isDarkTheme ? '#3c3c3c' : '#e8e8e8';
              }}
            >
              Edit
            </button>
          )}

          {onLessonDelete && (
            <button
              onClick={() => onLessonDelete(lesson.id)}
              style={buttonStyle(isDarkTheme, 'danger')}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = isDarkTheme ? '#6a2a2a' : '#ffcdd2';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = isDarkTheme ? '#5a1d1d' : '#ffebee';
              }}
            >
              Delete
            </button>
          )}

          <button
            onClick={() => toggleLessonExpanded(lesson.id, lesson)}
            style={{
              ...buttonStyle(isDarkTheme),
              fontSize: '10px',
              padding: '2px 8px',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            <span style={{ transform: expandedIds.has(lesson.id) ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}>
              ▶
            </span>
            {expandedIds.has(lesson.id) ? 'Hide content' : 'Show content'}
          </button>

          {lesson.appliedTo && lesson.appliedTo.length > 0 && (
            <button
              onClick={() => setExpandedAppliedIds((prev) => {
                const next = new Set(prev);
                if (next.has(lesson.id)) next.delete(lesson.id);
                else next.add(lesson.id);
                return next;
              })}
              style={{
                ...buttonStyle(isDarkTheme),
                fontSize: '10px',
                padding: '2px 8px',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <span style={{ transform: expandedAppliedIds.has(lesson.id) ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}>
                ▶
              </span>
              Applied to ({lesson.appliedTo.length})
            </button>
          )}
        </div>

        {/* Content (expandable) */}
        {expandedIds.has(lesson.id) && (
          <pre
            style={{
              margin: '8px 0 0 0',
              padding: '10px',
              fontSize: '12px',
              lineHeight: '1.5',
              backgroundColor: isDarkTheme ? '#1e1e1e' : '#ffffff',
              border: `1px solid ${isDarkTheme ? '#3c3c3c' : '#e0e0e0'}`,
              borderRadius: '4px',
              color: isDarkTheme ? '#d4d4d4' : '#444444',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontFamily: 'inherit',
              overflow: 'auto',
              maxHeight: '300px',
            }}
          >
            {loadingContentIds.has(lesson.id)
              ? 'Loading...'
              : (lesson.content ? highlightText(lesson.content, isCurrentMatch) : 'No content available')}
          </pre>
        )}

        {/* Applied To (expandable list) */}
        {expandedAppliedIds.has(lesson.id) && lesson.appliedTo && lesson.appliedTo.length > 0 && (
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '8px' }}>
            {lesson.appliedTo.map((target, idx) => (
              <button
                key={idx}
                onClick={() => onNavigateToRun?.(target.runId, target.nodeId)}
                style={{
                  ...buttonStyle(isDarkTheme),
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = isDarkTheme ? '#4a4a4a' : '#d0d0d0';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = isDarkTheme ? '#3c3c3c' : '#e8e8e8';
                }}
                title={`Go to: ${target.runName}`}
              >
                <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M4.5 3A1.5 1.5 0 0 0 3 4.5v7A1.5 1.5 0 0 0 4.5 13h7a1.5 1.5 0 0 0 1.5-1.5v-3a.5.5 0 0 1 1 0v3A2.5 2.5 0 0 1 11.5 14h-7A2.5 2.5 0 0 1 2 11.5v-7A2.5 2.5 0 0 1 4.5 2h3a.5.5 0 0 1 0 1h-3z"/>
                  <path d="M10 2a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 .5.5v4a.5.5 0 0 1-1 0V2.707l-5.146 5.147a.5.5 0 0 1-.708-.708L13.293 2H10.5A.5.5 0 0 1 10 1.5z"/>
                </svg>
                {target.runName}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  };

  // Render a folder row and its contents (recursive)
  const renderFolder = (folder: FolderEntry, depth: number) => {
    const { path: folderPath, lesson_count: lessonCount } = folder;
    const isExpanded = expandedFolders.has(folderPath);
    const isLoading = loadingFolders.has(folderPath);
    const data = folderData.get(folderPath);
    // Extract display name from path (last segment)
    const segments = folderPath.replace(/\/$/, '').split('/');
    const displayName = segments[segments.length - 1] || folderPath;

    return (
      <div key={folderPath}>
        {/* Folder row */}
        <div
          onClick={() => toggleFolder(folderPath)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '8px 12px',
            paddingLeft: `${12 + depth * 16}px`,
            cursor: 'pointer',
            borderRadius: '4px',
            backgroundColor: isDarkTheme ? '#2d2d2d' : '#fafafa',
            border: `1px solid ${isDarkTheme ? '#3c3c3c' : '#e0e0e0'}`,
            fontSize: '13px',
            fontWeight: 500,
            color: isDarkTheme ? '#e5e5e5' : '#333333',
            userSelect: 'none',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = isDarkTheme ? '#353535' : '#f0f0f0';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = isDarkTheme ? '#2d2d2d' : '#fafafa';
          }}
        >
          <span style={{ width: 16, height: 16, display: 'inline-flex', alignItems: 'center' }}>
            {isExpanded ? (
              <svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="currentColor"><path d="M3.14645 5.64645C3.34171 5.45118 3.65829 5.45118 3.85355 5.64645L8 9.79289L12.1464 5.64645C12.3417 5.45118 12.6583 5.45118 12.8536 5.64645C13.0488 5.84171 13.0488 6.15829 12.8536 6.35355L8.35355 10.8536C8.15829 11.0488 7.84171 11.0488 7.64645 10.8536L3.14645 6.35355C2.95118 6.15829 2.95118 5.84171 3.14645 5.64645Z"/></svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="currentColor"><path d="M5.64645 3.14645C5.45118 3.34171 5.45118 3.65829 5.64645 3.85355L9.79289 8L5.64645 12.1464C5.45118 12.3417 5.45118 12.6583 5.64645 12.8536C5.84171 13.0488 6.15829 13.0488 6.35355 12.8536L10.8536 8.35355C11.0488 8.15829 11.0488 7.84171 10.8536 7.64645L6.35355 3.14645C6.15829 2.95118 5.84171 2.95118 5.64645 3.14645Z"/></svg>
            )}
          </span>
          <span style={{ width: 16, height: 16, display: 'inline-flex', alignItems: 'center' }}>
            {isExpanded ? (
              <svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="currentColor"><path d="M2 4.5V9.10022L2.92389 7.5C3.45979 6.5718 4.45017 6 5.52196 6L11.9146 6C11.7087 5.4174 11.1531 5 10.5 5H7C6.86739 5 6.74021 4.94732 6.64645 4.85355L4.93934 3.14645C4.84557 3.05268 4.71839 3 4.58579 3H3.5C2.67157 3 2 3.67157 2 4.5ZM7.06895 13.9953C7.04641 13.9984 7.02339 14 7 14H3.5C2.11929 14 1 12.8807 1 11.5V4.5C1 3.11929 2.11929 2 3.5 2H4.58579C4.98361 2 5.36514 2.15804 5.64645 2.43934L7.20711 4H10.5C11.724 4 12.7426 4.87965 12.958 6.04127C14.605 6.34148 15.5443 8.22106 14.6616 9.75L13.0766 12.4953C12.5407 13.4235 11.5503 13.9953 10.4785 13.9953H7.06895ZM5.52196 7C4.80743 7 4.14718 7.3812 3.78991 8L2.20492 10.7453C1.62757 11.7453 2.34926 12.9953 3.50396 12.9953L10.4785 12.9953C11.193 12.9953 11.8533 12.6141 12.2105 11.9953L13.7955 9.25C14.3729 8.25 13.6512 7 12.4965 7L5.52196 7Z"/></svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="currentColor"><path d="M2 4.5V6H5.58579C5.71839 6 5.84557 5.94732 5.93934 5.85355L7.29289 4.5L5.93934 3.14645C5.84557 3.05268 5.71839 3 5.58579 3H3.5C2.67157 3 2 3.67157 2 4.5ZM1 4.5C1 3.11929 2.11929 2 3.5 2H5.58579C5.98361 2 6.36514 2.15804 6.64645 2.43934L8.20711 4H12.5C13.8807 4 15 5.11929 15 6.5V11.5C15 12.8807 13.8807 14 12.5 14H3.5C2.11929 14 1 12.8807 1 11.5V4.5ZM2 7V11.5C2 12.3284 2.67157 13 3.5 13H12.5C13.3284 13 14 12.3284 14 11.5V6.5C14 5.67157 13.3284 5 12.5 5H8.20711L6.64645 6.56066C6.36514 6.84197 5.98361 7 5.58579 7H2Z"/></svg>
            )}
          </span>
          <span>{displayName}</span>
          <span style={{
            fontSize: '10px',
            padding: '1px 5px',
            borderRadius: '8px',
            backgroundColor: isDarkTheme ? '#3c3c3c' : '#e0e0e0',
            color: isDarkTheme ? '#999999' : '#666666',
            marginLeft: '4px',
          }}>
            {lessonCount}
          </span>
          {isLoading && <Spinner isDark={isDarkTheme} />}
        </div>

        {/* Expanded contents */}
        {isExpanded && data && (
          <div style={{ marginLeft: `${depth * 16}px`, marginTop: '4px' }}>
            {/* Sub-folders */}
            {data.folders.map((subFolder) => renderFolder(subFolder, depth + 1))}
            {/* Lessons in this folder */}
            {data.lessons.map((lesson) => (
              <div key={lesson.id} style={{ marginLeft: '16px', marginTop: '4px' }}>
                {renderLessonCard(lesson)}
              </div>
            ))}
            {data.folders.length === 0 && data.lessons.length === 0 && (
              <div style={{
                padding: '8px 16px',
                marginLeft: '16px',
                fontSize: '12px',
                color: isDarkTheme ? '#888888' : '#666666',
                fontStyle: 'italic',
              }}>
                Empty folder
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  // Render root-level content (lessons + folders from root)
  const renderRootContent = () => {
    const rootData = folderData.get('');
    const isRootLoading = loadingFolders.has('');

    if (apiKeyError) {
      return (
        <div
          style={{
            textAlign: 'center',
            padding: '60px 20px',
            color: isDarkTheme ? '#cccccc' : '#444444',
          }}
        >
          <div style={{ fontSize: '14px', marginBottom: '12px' }}>
            Unable to connect to the Lessons server.
          </div>
          <div style={{ fontSize: '13px', color: isDarkTheme ? '#888888' : '#666666' }}>
            To obtain an API key, send an e-mail to{' '}
            <a
              href="mailto:hello@sovara-labs.com"
              style={{ color: isDarkTheme ? '#4a9eff' : '#007acc' }}
            >
              hello@sovara-labs.com
            </a>
          </div>
        </div>
      );
    }

    if (isRootLoading && !rootData) {
      return (
        <div style={{
          textAlign: 'center',
          padding: '40px 20px',
          color: isDarkTheme ? '#888888' : '#666666',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '8px',
        }}>
          Loading...
          <Spinner isDark={isDarkTheme} />
        </div>
      );
    }

    if (!rootData) {
      return (
        <div style={{
          textAlign: 'center',
          padding: '40px 20px',
          color: isDarkTheme ? '#888888' : '#666666',
        }}>
          No lessons yet
        </div>
      );
    }

    const { folders, lessons } = rootData;
    if (folders.length === 0 && lessons.length === 0) {
      return (
        <div style={{
          textAlign: 'center',
          padding: '40px 20px',
          color: isDarkTheme ? '#888888' : '#666666',
        }}>
          No lessons yet
        </div>
      );
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {/* Folders first */}
        {folders.map((folder) => renderFolder(folder, 0))}
        {/* Root-level lessons */}
        {lessons.map((lesson) => renderLessonCard(lesson))}
      </div>
    );
  };

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        backgroundColor: isDarkTheme ? '#252525' : '#F0F0F0',
        color: isDarkTheme ? '#e5e5e5' : '#333333',
        fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Header with Search */}
      <div
        style={{
          padding: '18px 24px 16px 24px',
          borderBottom: `1px solid ${isDarkTheme ? '#3c3c3c' : '#e0e0e0'}`,
          backgroundColor: isDarkTheme ? '#252525' : '#F0F0F0',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <h2
            style={{
              margin: 0,
              fontSize: '18px',
              fontWeight: 600,
              color: isDarkTheme ? '#e5e5e5' : '#333333',
            }}
          >
            Lessons
          </h2>
          {onLessonCreate && (
            <button
              onClick={() => {
                setShowCreateModal(true);
                onClearValidation?.();
              }}
              style={{
                ...buttonStyle(isDarkTheme, 'primary'),
                padding: '6px 12px',
                fontSize: '12px',
                backgroundColor: '#43884e',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = '#3a7644';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = '#43884e';
              }}
            >
              + Add Lesson
            </button>
          )}
        </div>

        {/* Search Bar */}
        <div style={{ position: 'relative' }}>
          <svg
            style={{
              position: 'absolute',
              left: '10px',
              top: '50%',
              transform: 'translateY(-50%)',
              width: '14px',
              height: '14px',
              fill: isDarkTheme ? '#888888' : '#666666',
            }}
            viewBox="0 0 16 16"
          >
            <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001c.03.04.062.078.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1.007 1.007 0 0 0-.115-.1zM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search lessons... (Enter for next)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            style={{
              width: '100%',
              padding: '8px 70px 8px 32px',
              fontSize: '13px',
              border: `1px solid ${isDarkTheme ? '#3c3c3c' : '#d0d0d0'}`,
              borderRadius: '4px',
              backgroundColor: isDarkTheme ? '#2d2d2d' : '#ffffff',
              color: isDarkTheme ? '#e5e5e5' : '#333333',
              outline: 'none',
              boxSizing: 'border-box',
            }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor = isDarkTheme ? '#0e639c' : '#007acc';
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor = isDarkTheme ? '#3c3c3c' : '#d0d0d0';
            }}
          />
          {searchQuery && (
            <span
              style={{
                position: 'absolute',
                right: '10px',
                top: '50%',
                transform: 'translateY(-50%)',
                fontSize: '11px',
                color: matchingLessonIds.length > 0
                  ? (isDarkTheme ? '#888888' : '#666666')
                  : (isDarkTheme ? '#f48771' : '#d32f2f'),
                fontWeight: 500,
              }}
            >
              {matchingLessonIds.length > 0
                ? `${currentMatchIndex + 1}/${matchingLessonIds.length}`
                : 'No matches'}
            </span>
          )}
        </div>
      </div>

      {/* Folder Tree */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 24px 16px 24px' }}>
        {renderRootContent()}
      </div>

      {/* Create Modal */}
      {showCreateModal &&
        renderModal(
          'Create New Lesson',
          createForm,
          setCreateForm,
          handleCreate,
          handleCancelCreate
        )}

      {/* Edit Modal */}
      {editingId &&
        renderModal(
          'Edit Lesson',
          editForm,
          setEditForm,
          (force) => handleSaveEdit(editingId, force),
          handleCancelEdit
        )}
    </div>
  );
};
