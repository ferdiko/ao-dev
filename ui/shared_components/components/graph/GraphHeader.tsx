import React from 'react';
import { Lesson } from '../lessons/LessonsView';

interface GraphHeaderProps {
  runName: string;
  isDarkTheme: boolean;
  runId?: string;
  lessons?: Lesson[];
  lessonsAppliedCount?: number;
  onNavigateToLessons?: () => void;
  onNavigateToAppliedLessons?: () => void;
}

export const GraphHeader: React.FC<GraphHeaderProps> = ({
  runName,
  isDarkTheme,
  runId,
  lessons = [],
  lessonsAppliedCount,
  onNavigateToLessons,
  onNavigateToAppliedLessons,
}) => {
  // Count lessons extracted from this graph
  const lessonsExtractedFrom = runId
    ? lessons.filter((lesson) => lesson.extractedFrom?.runId === runId).length
    : 0;

  // Count lessons applied to this graph (from server, or fallback to filtering lessons)
  const lessonsAppliedTo = lessonsAppliedCount ?? (runId
    ? lessons.filter((lesson) => lesson.appliedTo?.some((app) => app.runId === runId)).length
    : 0);

  return (
    <div
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 150,
        height: 0,
        overflow: 'visible',
      }}
    >
      {/* Content wrapper with background */}
      <div
        style={{
          position: 'absolute',
          top: '8px',
          left: '12px',
          backgroundColor: isDarkTheme ? '#252525' : '#F0F0F0',
          padding: '12px 16px',
          borderRadius: '8px',
        }}
      >
        {/* Run Name */}
        <div
          style={{
            fontSize: '18px',
            fontWeight: 600,
            color: isDarkTheme ? '#e5e5e5' : '#333333',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {runName || 'Untitled'}
        </div>

        {/* Horizontal Line */}
        {runId && (
          <div
            style={{
              width: '280px',
              height: '1.5px',
              backgroundColor: isDarkTheme ? '#3c3c3c' : '#d0d0d0',
              margin: '8px 0',
            }}
          />
        )}

        {/* Prior Stats */}
        {runId && (
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '15px',
              fontWeight: 400,
            }}
          >
            <span
              style={{
                cursor: onNavigateToLessons ? 'pointer' : 'default',
                color: isDarkTheme ? '#4da6ff' : '#007acc',
                transition: 'color 0.2s',
              }}
              onClick={onNavigateToLessons}
              onMouseEnter={(e) => {
                if (onNavigateToLessons) e.currentTarget.style.color = isDarkTheme ? '#6bb8ff' : '#005a9e';
              }}
              onMouseLeave={(e) => {
                if (onNavigateToLessons) e.currentTarget.style.color = isDarkTheme ? '#4da6ff' : '#007acc';
              }}
              title="View all priors"
            >
              {lessonsExtractedFrom} prior{lessonsExtractedFrom !== 1 ? 's' : ''} extracted
            </span>
            <span style={{ color: isDarkTheme ? '#3c7ab8' : '#99c9e8' }}>|</span>
            <span
              style={{
                cursor: onNavigateToAppliedLessons ? 'pointer' : 'default',
                color: isDarkTheme ? '#4da6ff' : '#007acc',
                transition: 'color 0.2s',
              }}
              onClick={onNavigateToAppliedLessons}
              onMouseEnter={(e) => {
                if (onNavigateToAppliedLessons) e.currentTarget.style.color = isDarkTheme ? '#6bb8ff' : '#005a9e';
              }}
              onMouseLeave={(e) => {
                if (onNavigateToAppliedLessons) e.currentTarget.style.color = isDarkTheme ? '#4da6ff' : '#007acc';
              }}
              title="View applied priors"
            >
              {lessonsAppliedTo} prior{lessonsAppliedTo !== 1 ? 's' : ''} applied
            </span>
          </div>
        )}
      </div>
    </div>
  );
};
