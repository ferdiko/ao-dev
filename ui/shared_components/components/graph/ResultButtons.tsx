import React from 'react';

interface ResultButtonsProps {
  currentResult: string;
  sessionId: string;
  isDarkTheme: boolean;
  onResultChange: (result: string) => void;
}

export const ResultButtons: React.FC<ResultButtonsProps> = ({
  currentResult,
  sessionId,
  isDarkTheme,
  onResultChange,
}) => {
  const isSelected = (value: string) => currentResult === value;

  const buttonBaseStyle: React.CSSProperties = {
    padding: '8px 16px',
    fontSize: '13px',
    fontWeight: 500,
    border: 'none',
    borderRadius: '6px',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  };

  const greenColor = '#4caf50';
  const redColor = '#f44336';

  const satisfactoryStyle: React.CSSProperties = {
    ...buttonBaseStyle,
    backgroundColor: isSelected('Satisfactory') ? greenColor : 'transparent',
    color: isSelected('Satisfactory') ? '#ffffff' : greenColor,
    border: `2px solid ${greenColor}`,
  };

  const failedStyle: React.CSSProperties = {
    ...buttonBaseStyle,
    backgroundColor: isSelected('Failed') ? redColor : 'transparent',
    color: isSelected('Failed') ? '#ffffff' : redColor,
    border: `2px solid ${redColor}`,
  };

  return (
    <div
      style={{
        position: 'fixed',
        bottom: '20px',
        right: '80px', // Account for the button column on the right
        display: 'flex',
        gap: '8px',
        zIndex: 1000,
        padding: '8px',
        backgroundColor: isDarkTheme ? 'rgba(30, 30, 30, 0.95)' : 'rgba(255, 255, 255, 0.95)',
        borderRadius: '8px',
        boxShadow: '0 2px 6px rgba(0, 0, 0, 0.15)',
        border: `1px solid ${isDarkTheme ? '#3c3c3c' : '#e0e0e0'}`,
      }}
    >
      <button
        style={satisfactoryStyle}
        onClick={() => onResultChange(isSelected('Satisfactory') ? '' : 'Satisfactory')}
        onMouseEnter={(e) => {
          if (!isSelected('Satisfactory')) {
            e.currentTarget.style.backgroundColor = 'rgba(76, 175, 80, 0.15)';
          }
        }}
        onMouseLeave={(e) => {
          if (!isSelected('Satisfactory')) {
            e.currentTarget.style.backgroundColor = 'transparent';
          }
        }}
        title="Mark as Satisfactory"
      >
        {/* Checkmark icon */}
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
          <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z"/>
        </svg>
      </button>

      <button
        style={failedStyle}
        onClick={() => onResultChange(isSelected('Failed') ? '' : 'Failed')}
        onMouseEnter={(e) => {
          if (!isSelected('Failed')) {
            e.currentTarget.style.backgroundColor = 'rgba(244, 67, 54, 0.15)';
          }
        }}
        onMouseLeave={(e) => {
          if (!isSelected('Failed')) {
            e.currentTarget.style.backgroundColor = 'transparent';
          }
        }}
        title="Mark as Failed"
      >
        {/* X icon */}
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
          <path d="M3.72 3.72a.75.75 0 011.06 0L8 6.94l3.22-3.22a.75.75 0 111.06 1.06L9.06 8l3.22 3.22a.75.75 0 11-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 01-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 010-1.06z"/>
        </svg>
      </button>
    </div>
  );
};
