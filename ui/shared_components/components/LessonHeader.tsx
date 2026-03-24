import React, { useState, useRef, useEffect } from 'react';
import { LessonSummary } from '../types';

interface LessonHeaderProps {
  lessonName: string;
  lessonId: string;
  isDarkTheme: boolean;
  lessons: LessonSummary[];
  hasUnsavedChanges: boolean;
  showPreview: boolean;
  saveStatus: 'idle' | 'saving' | 'saved' | 'error';
  onNavigateToLesson: (lesson: LessonSummary) => void;
  onTogglePreview: () => void;
  onSave: () => void;
}

export const LessonHeader: React.FC<LessonHeaderProps> = ({
  lessonName,
  lessonId,
  isDarkTheme,
  lessons = [],
  hasUnsavedChanges,
  showPreview,
  saveStatus,
  onNavigateToLesson,
  onTogglePreview,
  onSave,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      setTimeout(() => searchInputRef.current?.focus(), 0);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  // Filter lessons by search
  const filteredLessons = lessons.filter((lesson) => {
    if (!searchQuery.trim()) return true;
    return lesson.name.toLowerCase().includes(searchQuery.toLowerCase());
  });

  // VS Code CSS variables for theme-aware colors
  const colors = {
    text: 'var(--vscode-foreground)',
    textMuted: 'var(--vscode-descriptionForeground)',
    border: 'var(--vscode-panel-border, var(--vscode-widget-border))',
    bg: 'var(--vscode-sideBar-background, var(--vscode-editor-background))',
    bgHover: 'var(--vscode-list-hoverBackground)',
    inputBg: 'var(--vscode-input-background)',
    dropdownBg: 'var(--vscode-dropdown-background, var(--vscode-editor-background))',
  };

  const handleLessonClick = (lesson: LessonSummary) => {
    setIsOpen(false);
    setSearchQuery('');
    onNavigateToLesson(lesson);
  };

  const iconButtonStyle: React.CSSProperties = {
    background: 'transparent',
    border: 'none',
    cursor: 'pointer',
    padding: '4px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: '4px',
    color: colors.text,
  };

  const disabledIconButtonStyle: React.CSSProperties = {
    ...iconButtonStyle,
    opacity: 0.4,
    cursor: 'not-allowed',
  };

  return (
    <div
      ref={dropdownRef}
      style={{
        padding: '9px 16px 0 16px',
        position: 'relative',
      }}
    >
      {/* Title Row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        {/* Left: Name + Chevron */}
        <div
          onClick={() => setIsOpen(!isOpen)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            cursor: 'pointer',
            userSelect: 'none',
            flex: 1,
            minWidth: 0,
          }}
        >
          <span
            style={{
              fontSize: '13px',
              fontWeight: 500,
              color: colors.text,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {lessonName || 'Untitled'}
          </span>
          {/* Chevron Icon */}
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill={colors.text}
            style={{
              transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 0.15s ease',
              flexShrink: 0,
            }}
          >
            <path d="M4.957 5.543L8 8.586l3.043-3.043.914.914L8 10.414 4.043 6.457l.914-.914z" />
          </svg>
        </div>

        {/* Right: Action Icons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginLeft: '12px' }}>
          {/* Preview Toggle */}
          <button
            onClick={onTogglePreview}
            style={iconButtonStyle}
            title={showPreview ? 'Edit' : 'Preview'}
          >
            <i
              className={showPreview ? 'codicon codicon-edit' : 'codicon codicon-open-preview'}
              style={{ fontSize: '16px' }}
            />
          </button>

          {/* Save Button */}
          <button
            onClick={onSave}
            disabled={!hasUnsavedChanges || saveStatus === 'saving'}
            style={hasUnsavedChanges && saveStatus !== 'saving' ? iconButtonStyle : disabledIconButtonStyle}
            title={
              saveStatus === 'saving' ? 'Saving...' :
              saveStatus === 'saved' ? 'Saved!' :
              saveStatus === 'error' ? 'Error saving' :
              'Save'
            }
          >
            <i
              className="codicon codicon-save"
              style={{ fontSize: '16px' }}
            />
          </button>
        </div>
      </div>

      {/* Horizontal Line */}
      <div
        style={{
          width: 'calc(100% + 32px)',
          height: '1px',
          backgroundColor: colors.border,
          margin: '8px 0',
          marginLeft: '-16px',
        }}
      />

      {/* Dropdown Panel */}
      {isOpen && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: '12px',
            width: '280px',
            maxHeight: '400px',
            backgroundColor: colors.dropdownBg,
            border: `1px solid ${colors.border}`,
            borderRadius: '6px',
            boxShadow: isDarkTheme
              ? '0 4px 16px rgba(0, 0, 0, 0.4)'
              : '0 4px 16px rgba(0, 0, 0, 0.15)',
            zIndex: 1000,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* Search Input */}
          <div
            style={{
              padding: '8px',
              borderBottom: `1px solid ${colors.border}`,
            }}
          >
            <input
              ref={searchInputRef}
              type="text"
              placeholder="Search lessons..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                padding: '6px 8px',
                fontSize: '12px',
                border: `1px solid ${colors.border}`,
                borderRadius: '4px',
                backgroundColor: colors.inputBg,
                color: colors.text,
                outline: 'none',
                boxSizing: 'border-box',
              }}
              onFocus={(e) => {
                e.target.style.borderColor = isDarkTheme ? '#0e639c' : '#007acc';
              }}
              onBlur={(e) => {
                e.target.style.borderColor = colors.border;
              }}
            />
          </div>

          {/* Lessons List */}
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: '4px 0',
            }}
          >
            {filteredLessons.length === 0 ? (
              <div
                style={{
                  padding: '12px 16px',
                  fontSize: '12px',
                  color: colors.textMuted,
                  textAlign: 'center',
                }}
              >
                No lessons found
              </div>
            ) : (
              filteredLessons.map((lesson) => (
                <div
                  key={lesson.id}
                  onClick={() => handleLessonClick(lesson)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '6px 12px',
                    cursor: 'pointer',
                    backgroundColor:
                      lesson.id === lessonId ? colors.bgHover : 'transparent',
                  }}
                  onMouseEnter={(e) => {
                    if (lesson.id !== lessonId) {
                      e.currentTarget.style.backgroundColor = colors.bgHover;
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (lesson.id !== lessonId) {
                      e.currentTarget.style.backgroundColor = 'transparent';
                    }
                  }}
                >
                  <span
                    style={{
                      fontSize: '12px',
                      color: colors.text,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      flex: 1,
                      fontWeight: lesson.id === lessonId ? 600 : 400,
                    }}
                  >
                    {lesson.name || 'Untitled'}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};
