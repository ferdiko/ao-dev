import React from 'react';
import { Prior } from '../priors/PriorsView';

interface GraphHeaderProps {
  runName: string;
  isDarkTheme: boolean;
  runId?: string;
  priors?: Prior[];
  priorsAppliedCount?: number;
  onNavigateToPriors?: () => void;
  onNavigateToAppliedPriors?: () => void;
}

export const GraphHeader: React.FC<GraphHeaderProps> = ({
  runName,
  isDarkTheme,
  runId,
  priors = [],
  priorsAppliedCount,
  onNavigateToPriors,
  onNavigateToAppliedPriors,
}) => {
  // Count priors extracted from this graph
  const priorsExtractedFrom = runId
    ? priors.filter((prior) => prior.extractedFrom?.runId === runId).length
    : 0;

  // Count priors applied to this graph (from server, or fallback to filtering priors)
  const priorsAppliedTo = priorsAppliedCount ?? (runId
    ? priors.filter((prior) => prior.appliedTo?.some((app) => app.runId === runId)).length
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
                cursor: onNavigateToPriors ? 'pointer' : 'default',
                color: isDarkTheme ? '#4da6ff' : '#007acc',
                transition: 'color 0.2s',
              }}
              onClick={onNavigateToPriors}
              onMouseEnter={(e) => {
                if (onNavigateToPriors) e.currentTarget.style.color = isDarkTheme ? '#6bb8ff' : '#005a9e';
              }}
              onMouseLeave={(e) => {
                if (onNavigateToPriors) e.currentTarget.style.color = isDarkTheme ? '#4da6ff' : '#007acc';
              }}
              title="View all priors"
            >
              {priorsExtractedFrom} prior{priorsExtractedFrom !== 1 ? 's' : ''} extracted
            </span>
            <span style={{ color: isDarkTheme ? '#3c7ab8' : '#99c9e8' }}>|</span>
            <span
              style={{
                cursor: onNavigateToAppliedPriors ? 'pointer' : 'default',
                color: isDarkTheme ? '#4da6ff' : '#007acc',
                transition: 'color 0.2s',
              }}
              onClick={onNavigateToAppliedPriors}
              onMouseEnter={(e) => {
                if (onNavigateToAppliedPriors) e.currentTarget.style.color = isDarkTheme ? '#6bb8ff' : '#005a9e';
              }}
              onMouseLeave={(e) => {
                if (onNavigateToAppliedPriors) e.currentTarget.style.color = isDarkTheme ? '#4da6ff' : '#007acc';
              }}
              title="View applied priors"
            >
              {priorsAppliedTo} prior{priorsAppliedTo !== 1 ? 's' : ''} applied
            </span>
          </div>
        )}
      </div>
    </div>
  );
};
