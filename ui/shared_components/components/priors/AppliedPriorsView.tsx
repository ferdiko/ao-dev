import React, { useState, useEffect } from 'react';
import { Prior } from './PriorsView';

interface AppliedPriorsViewProps {
  priors: Prior[];
  isDarkTheme: boolean;
  onBack: () => void;
  onFetchPriorContent?: (id: string) => void;
  priorContentUpdate?: { id: string; content: string } | null;
}

export const AppliedPriorsView: React.FC<AppliedPriorsViewProps> = ({
  priors,
  isDarkTheme,
  onBack,
  onFetchPriorContent,
  priorContentUpdate,
}) => {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [loadingContentIds, setLoadingContentIds] = useState<Set<string>>(new Set());
  const [priorContents, setPriorContents] = useState<Map<string, string>>(new Map());

  // Process incoming prior content updates
  useEffect(() => {
    if (!priorContentUpdate) return;
    const { id, content } = priorContentUpdate;
    setLoadingContentIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
    setPriorContents((prev) => new Map(prev).set(id, content));
  }, [priorContentUpdate]);

  const toggleExpanded = (id: string, prior: Prior) => {
    const isExpanding = !expandedIds.has(id);
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    if (isExpanding && !prior.content && !priorContents.has(id) && onFetchPriorContent) {
      setLoadingContentIds((prev) => new Set(prev).add(id));
      onFetchPriorContent(id);
    }
  };

  const getContent = (prior: Prior): string => {
    return priorContents.get(prior.id) || prior.content || '';
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
      {/* Header */}
      <div
        style={{
          padding: '18px 24px 16px 24px',
          borderBottom: `1px solid ${isDarkTheme ? '#3c3c3c' : '#e0e0e0'}`,
          backgroundColor: isDarkTheme ? '#252525' : '#F0F0F0',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
        }}
      >
        <button
          onClick={onBack}
          style={{
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            padding: '4px',
            display: 'flex',
            alignItems: 'center',
            color: isDarkTheme ? '#cccccc' : '#555555',
            borderRadius: '4px',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = isDarkTheme ? '#3c3c3c' : '#e0e0e0';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'transparent';
          }}
          title="Back to graph"
        >
          <svg width="20" height="20" viewBox="0 0 16 16" fill="currentColor">
            <path d="M5.928 7.976l4.357-4.357-.618-.62L5 7.671v.61l4.667 4.672.618-.62-4.357-4.357z" />
          </svg>
        </button>
        <h2
          style={{
            margin: 0,
            fontSize: '18px',
            fontWeight: 600,
            color: isDarkTheme ? '#e5e5e5' : '#333333',
          }}
        >
          Applied Priors ({priors.length})
        </h2>
      </div>

      {/* Prior List */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 24px' }}>
        {priors.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              padding: '40px 20px',
              color: isDarkTheme ? '#888888' : '#666666',
            }}
          >
            No priors applied to this run
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {priors.map((prior) => (
              <div
                key={prior.id}
                style={{
                  backgroundColor: isDarkTheme ? '#2d2d2d' : '#fafafa',
                  border: `1px solid ${isDarkTheme ? '#3c3c3c' : '#e0e0e0'}`,
                  borderRadius: '6px',
                  padding: '14px 16px',
                }}
              >
                {/* Name and Path */}
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <h4
                    style={{
                      margin: 0,
                      fontSize: '14px',
                      fontWeight: 600,
                      color: isDarkTheme ? '#e5e5e5' : '#333333',
                    }}
                  >
                    {prior.name}
                  </h4>
                  {prior.path && (
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
                      {prior.path}
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
                  {prior.summary}
                </p>

                {/* Expand content button */}
                <button
                  onClick={() => toggleExpanded(prior.id, prior)}
                  style={{
                    padding: '2px 8px',
                    fontSize: '10px',
                    fontWeight: 500,
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    backgroundColor: isDarkTheme ? '#3c3c3c' : '#e8e8e8',
                    color: isDarkTheme ? '#cccccc' : '#333333',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    transition: 'background-color 0.15s ease',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = isDarkTheme ? '#4a4a4a' : '#d0d0d0';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = isDarkTheme ? '#3c3c3c' : '#e8e8e8';
                  }}
                >
                  <span style={{ transform: expandedIds.has(prior.id) ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}>
                    &#9654;
                  </span>
                  {expandedIds.has(prior.id) ? 'Hide content' : 'Show content'}
                </button>

                {/* Content (expandable) */}
                {expandedIds.has(prior.id) && (
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
                    {loadingContentIds.has(prior.id)
                      ? 'Loading...'
                      : (getContent(prior) || 'No content available')}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
