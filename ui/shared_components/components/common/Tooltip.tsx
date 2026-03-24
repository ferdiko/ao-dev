import React, { useState, useRef, useEffect } from 'react';

interface TooltipProps {
  content: string;
  children: React.ReactNode;
  position?: 'left' | 'right' | 'top' | 'bottom';
  isDarkTheme?: boolean;
}

export const Tooltip: React.FC<TooltipProps> = ({
  content,
  children,
  position = 'left',
  isDarkTheme = false,
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const [tooltipStyle, setTooltipStyle] = useState<React.CSSProperties>({});
  const containerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isVisible && containerRef.current && tooltipRef.current) {
      const containerRect = containerRef.current.getBoundingClientRect();
      const tooltipRect = tooltipRef.current.getBoundingClientRect();

      let style: React.CSSProperties = {};

      switch (position) {
        case 'left':
          style = {
            right: '100%',
            top: '50%',
            transform: 'translateY(-50%)',
            marginRight: '8px',
          };
          break;
        case 'right':
          style = {
            left: '100%',
            top: '50%',
            transform: 'translateY(-50%)',
            marginLeft: '8px',
          };
          break;
        case 'top':
          style = {
            bottom: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            marginBottom: '8px',
          };
          break;
        case 'bottom':
          style = {
            top: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            marginTop: '8px',
          };
          break;
      }

      setTooltipStyle(style);
    }
  }, [isVisible, position]);

  const baseTooltipStyle: React.CSSProperties = {
    position: 'absolute',
    padding: '4px 8px',
    backgroundColor: isDarkTheme ? '#252526' : '#f5f5f5',
    color: isDarkTheme ? '#cccccc' : '#333333',
    border: `1px solid ${isDarkTheme ? '#454545' : '#d0d0d0'}`,
    borderRadius: '3px',
    fontSize: '12px',
    whiteSpace: 'nowrap',
    zIndex: 10000,
    pointerEvents: 'none',
    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.15)',
  };

  return (
    <div
      ref={containerRef}
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={() => setIsVisible(true)}
      onMouseLeave={() => setIsVisible(false)}
    >
      {children}
      {isVisible && (
        <div
          ref={tooltipRef}
          style={{ ...baseTooltipStyle, ...tooltipStyle }}
        >
          {content}
        </div>
      )}
    </div>
  );
};
