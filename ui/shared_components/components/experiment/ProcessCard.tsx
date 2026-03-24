import React from 'react';
import styles from './ProcessCard.module.css';
import { ProcessInfo } from '../../types';
import { getDateOnly } from '../../utils/timeSpan';


export interface ProcessCardProps {
  process: ProcessInfo;
  isHovered: boolean;
  onClick?: () => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
  isDarkTheme: boolean;
  nodeColors: string[];
}

export const ProcessCard: React.FC<ProcessCardProps> = React.memo(
  ({
    process,
    isHovered,
    onClick,
    onMouseEnter,
    onMouseLeave,
    isDarkTheme,
    nodeColors,
  }) => {
    // Debug logging
    // console.log(`ProcessCard render for ${process.session_id}:`, { nodeColors, color_preview: process.color_preview });

    const handleClick = async () => {
      // Call original onClick (experiment clicks now handled by server)
      onClick?.();
    };

    // Check if the workflow is currently running
    const isRunning = process.status === 'running';

    // Generate a random animation delay between 0-2s for human-like effect
    const [animationDelay] = React.useState(() => Math.random() * 2);

    // Determine border color based on result
    const getBorderColor = () => {
      if (isRunning) return '#4a9eff'; // Blue for running state
      const result = process.result?.toLowerCase();
      if (result === 'failed') return '#e05252'; // Red (from erase button)
      if (result === 'satisfactory') return '#7fc17b'; // Green (from rerun button)
      return isDarkTheme ? '#6B6B6B' : '#CCCCCC'; // Neutral (default)
    };

    return (
      <div
        className={[
          styles.card,
          isDarkTheme ? styles.dark : styles.light,
          isHovered ? styles.hovered : "",
          isRunning ? styles.running : "",
        ].join(" ")}
        onClick={handleClick}
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
        tabIndex={0}
        style={{
          position: 'relative',
          overflow: 'hidden',
          borderColor: getBorderColor(),
          ...(isRunning && {
            animationDelay: `${animationDelay}s`,
          }),
        }}
      >
        {/* Progress bar background */}
        {nodeColors.length > 0 && (
          <div style={{
            position: 'absolute',
            top: 0,
            left: 0,
            bottom: 0,
            display: 'flex',
            zIndex: 0,
          }}>
            {nodeColors.map((color, i) => {
              const segmentWidth = 8;
              return (
                <div
                  key={i}
                  style={{
                    width: `${segmentWidth}px`,
                    minWidth: '1px',
                    height: '100%',
                    backgroundColor: color || "#00c542",
                    opacity: 0.15,
                  }}
                />
              );
            })}
          </div>
        )}

        {/* Content layer */}
        <div style={{ position: 'relative', zIndex: 1 }}>
          <div
            className={styles.headerRow}
            style={{ display: "flex", alignItems: "center", width: "100%", justifyContent: "space-between", gap: 8 }}
          >
            <div className={styles.title} style={{ textAlign: "left", flex: 1, minWidth: 0, wordBreak: 'break-word', whiteSpace: 'normal' }}>
              {process.run_name ? process.run_name : "Untitled"}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', flexShrink: 0, gap: 8, minWidth: 0, justifyContent: 'flex-end' }}>
              <div
                className={styles.date}
                style={{ color: "#aaa", whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 60 }}
              >
                {process.timestamp}
                {/* Uncomment the line below if you want to use getDateOnly*/}
                {/* Returns only the date part (YYYY-MM-DD) from a timestamp like '2024-06-21 12:00:00' */}
                {/* {getDateOnly(process.timestamp)} */}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }
);
