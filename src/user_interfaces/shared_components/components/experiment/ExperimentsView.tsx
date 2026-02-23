import React, { useState, useLayoutEffect } from 'react';
import { ProcessInfo } from '../../types';

// interface UserInfo {
//   displayName?: string;
//   avatarUrl?: string;
//   email?: string;
// }

interface ExperimentsViewProps {
  similarProcesses: ProcessInfo[];
  runningProcesses: ProcessInfo[];
  finishedProcesses: ProcessInfo[];
  onCardClick?: (process: ProcessInfo) => void;
  isDarkTheme?: boolean;
  // user?: UserInfo;
  // onLogout?: () => void;
  // onLogin?: () => void;
  showHeader?: boolean;
  onModeChange?: (mode: 'Local' | 'Remote') => void;
  currentMode?: 'Local' | 'Remote' | null;
  onLessonsClick?: () => void;
  onRefresh?: () => void;
}

export const ExperimentsView: React.FC<ExperimentsViewProps> = ({
  similarProcesses,
  runningProcesses,
  finishedProcesses,
  onCardClick,
  isDarkTheme = false,
  // user,
  // onLogout,
  // onLogin,
  showHeader = false,
  onModeChange,
  currentMode = null,
  onLessonsClick,
  onRefresh,
}) => {
  const [hoveredCards, setHoveredCards] = useState<Set<string>>(new Set());
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['running', 'finished']));
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // Section sizes (percentages of available height)
  const [runningSizePercent, setRunningSizePercent] = useState(30);
  const [finishedSizePercent, setFinishedSizePercent] = useState(70);

  const [resizing, setResizing] = useState<'running' | 'finished' | null>(null);
  const [startY, setStartY] = useState(0);
  const [startSize, setStartSize] = useState(0);

  // Sign out icon from VSCode codicons
  // const IconSignOut = ({ size = 16 }: { size?: number }) => (
  //   <svg width={size} height={size} viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="currentColor">
  //     <path d="M4.5 2C3.119 2 2 3.119 2 4.5V11.5C2 12.881 3.119 14 4.5 14H9.5C9.776 14 10 13.776 10 13.5C10 13.224 9.776 13 9.5 13H4.5C3.672 13 3 12.328 3 11.5V4.5C3 3.672 3.672 3 4.5 3H9.5C9.776 3 10 2.776 10 2.5C10 2.224 9.776 2 9.5 2H4.5Z"/>
  //     <path d="M13.854 7.646L10.854 4.646C10.659 4.451 10.342 4.451 10.147 4.646C9.952 4.841 9.952 5.158 10.147 5.353L12.293 7.499H5.5C5.224 7.499 5 7.723 5 7.999C5 8.275 5.224 8.499 5.5 8.499H12.293L10.147 10.645C9.952 10.84 9.952 11.157 10.147 11.352C10.342 11.547 10.659 11.547 10.854 11.352L13.854 8.352C14.049 8.157 14.049 7.841 13.854 7.646Z"/>
  //   </svg>
  // );

  // const IconGoogle = ({ size = 20 }: { size?: number }) => (
  //   <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width={size} height={size}>
  //     <path fill="#FFC107" d="M43.611,20.083H42V20H24v8h11.303c-1.649,4.657-6.08,8-11.303,8c-6.627,0-12-5.373-12-12c0-6.627,5.373-12,12-12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C12.955,4,4,12.955,4,24c0,11.045,8.955,20,20,20c11.045,0,20-8.955,20-20C44,22.659,43.862,21.35,43.611,20.083z"/>
  //     <path fill="#FF3D00" d="M6.306,14.691l6.571,4.819C14.655,15.108,18.961,12,24,12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C16.318,4,9.656,8.337,6.306,14.691z"/>
  //     <path fill="#4CAF50" d="M24,44c5.166,0,9.86-1.977,13.409-5.192l-6.19-5.238C29.211,35.091,26.715,36,24,36c-5.202,0-9.619-3.317-11.283-7.946l-6.522,5.025C9.505,39.556,16.227,44,24,44z"/>
  //     <path fill="#1976D2" d="M43.611,20.083H42V20H24v8h11.303c-0.792,2.237-2.231,4.166-4.087,5.571c0.001-0.001,0.002-0.001,0.003-0.002l6.19,5.238C36.971,39.205,44,34,44,24C44,22.659,43.862,21.35,43.611,20.083z"/>
  //   </svg>
  // );

  // Request experiment list when component mounts and is ready to display data
  useLayoutEffect(() => {
    // Check if we're in a VS Code environment
    if (typeof window !== 'undefined' && (window as any).vscode) {
      (window as any).vscode.postMessage({ type: 'requestExperimentRefresh' });
    }
  }, []); // Empty dependency array - only runs once on mount

  // Handle resize dragging
  const handleMouseDown = (section: 'running' | 'finished', e: React.MouseEvent) => {
    e.preventDefault();
    setResizing(section);
    setStartY(e.clientY);
    setStartSize(section === 'running' ? runningSizePercent : finishedSizePercent);
  };

  const handleMouseMove = (e: MouseEvent) => {
    if (!resizing) return;

    const containerHeight = window.innerHeight - footerHeight - 100; // Approximate available height
    const deltaY = e.clientY - startY;
    const deltaPercent = (deltaY / containerHeight) * 100;

    if (resizing === 'running') {
      // Running section: constrain so finished still has space
      const maxRunning = 100 - 10; // Leave at least 10% for finished
      const newSize = Math.max(10, Math.min(maxRunning, startSize + deltaPercent));
      setRunningSizePercent(newSize);
      // Adjust finished to take remaining space
      setFinishedSizePercent(100 - newSize);
    } else if (resizing === 'finished') {
      // Finished section: constrain so running still has space
      const maxFinished = 100 - runningSizePercent;
      const newSize = Math.max(10, Math.min(maxFinished, startSize + deltaPercent));
      setFinishedSizePercent(newSize);
    }
  };

  const handleMouseUp = () => {
    setResizing(null);
  };

  // Add/remove mouse event listeners for dragging
  useLayoutEffect(() => {
    if (resizing) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      return () => {
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
      };
    }
  }, [resizing, startY, startSize]);

  // Footer layout constants
  const footerHeight = 60; // px

  // Debug logging
  // console.log('ExperimentsView render - runningProcesses:', runningProcesses);
  // console.log('ExperimentsView render - finishedProcesses:', finishedProcesses);
  const containerStyle: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    backgroundColor: 'var(--vscode-sideBar-background, var(--vscode-editor-background))',
    color: 'var(--vscode-foreground)',
    fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
  };

  // const userSectionContainerStyle: React.CSSProperties = {
  //   position: 'fixed',
  //   left: 0,
  //   right: 0,
  //   bottom: 0,
  //   backgroundColor: isDarkTheme ? '#1e1e1e' : '#ffffff',
  //   borderTop: `1px solid ${isDarkTheme ? '#2b2b2b' : '#e5e5e5'}`,
  //   zIndex: 10,
  //   padding: '8px 16px',
  // };

  // const userRowStyle: React.CSSProperties = {
  //   display: 'flex',
  //   alignItems: 'center',
  //   gap: '12px',
  //   cursor: user ? 'pointer' : 'default',
  //   flex: '1',
  // };

  // const loginButtonStyle: React.CSSProperties = {
  //   width: '100%',
  //   padding: '6px 16px',
  //   fontSize: '13px',
  //   fontWeight: 'normal',
  //   color: isDarkTheme ? '#cccccc' : '#333333',
  //   backgroundColor: isDarkTheme ? '#1e1e1e' : '#ffffff',
  //   border: `1px solid ${isDarkTheme ? '#3c3c3c' : '#cccccc'}`,
  //   borderRadius: 0,
  //   cursor: 'pointer',
  //   display: 'flex',
  //   alignItems: 'center',
  //   justifyContent: 'center',
  //   gap: 8,
  //   transition: 'background-color 0.1s',
  // };

  // const avatarStyle: React.CSSProperties = {
  //   width: 44,
  //   height: 44,
  //   borderRadius: '50%',
  //   objectFit: 'cover',
  //   backgroundColor: '#ddd',
  // };

  // const nameBlockStyle: React.CSSProperties = {
  //   display: 'flex',
  //   flexDirection: 'column',
  //   lineHeight: 1,
  //   minWidth: 0,
  // };

  // const nameStyle: React.CSSProperties = {
  //   fontSize: 14,
  //   fontWeight: 600,
  //   color: isDarkTheme ? '#FFFFFF' : '#111111',
  //   whiteSpace: 'nowrap',
  //   overflow: 'hidden',
  //   textOverflow: 'ellipsis',
  // };

  // const emailStyle: React.CSSProperties = {
  //   marginTop:5,
  //   fontSize: 12,
  //   color: isDarkTheme ? '#BBBBBB' : '#666666',
  //   whiteSpace: 'nowrap',
  //   overflow: 'hidden',
  //   textOverflow: 'ellipsis',
  // };

  const handleCardHover = (cardId: string, isEntering: boolean) => {
    setHoveredCards((prev) => {
      const newSet = new Set(prev);
      if (isEntering) {
        newSet.add(cardId);
      } else {
        newSet.delete(cardId);
      }
      return newSet;
    });
  };

  // const handleLogoutClick = () => {
  //   if (onLogout) onLogout();
  //   else console.log('Logout clicked (no handler provided)');
  // };

  // const handleLoginClick = () => {
  //   if (onLogin) onLogin();
  //   else console.log('Login clicked (no handler provided)');
  // };

  const toggleSection = (sectionId: string) => {
    setExpandedSections((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(sectionId)) {
        newSet.delete(sectionId);
      } else {
        newSet.add(sectionId);
      }
      return newSet;
    });
  };

  const handleModeChange = (mode: 'Local' | 'Remote') => {
    console.log(mode);
    setDropdownOpen(false);

    // Call parent handler to send message to server
    if (onModeChange) {
      onModeChange(mode);
    }
  };


  const renderExperimentSection = (
    processes: ProcessInfo[],
    sectionTitle: string,
    sectionPrefix: string,
    sizePercent: number,
    showResizeHandle: boolean
  ) => {
    const isExpanded = expandedSections.has(sectionPrefix);

    const sectionHeaderStyle: React.CSSProperties = {
      display: 'flex',
      alignItems: 'center',
      gap: '4px',
      padding: '4px 16px',
      fontSize: '11px',
      fontWeight: 700,
      letterSpacing: '0.5px',
      textTransform: 'uppercase',
      color: 'var(--vscode-sideBarSectionHeader-foreground, var(--vscode-foreground))',
      cursor: 'pointer',
      userSelect: 'none',
      fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
    };

    const chevronStyle: React.CSSProperties = {
      fontSize: '16px',
      transition: 'transform 0.1s ease',
      display: 'flex',
      alignItems: 'center',
    };

    const listContainerStyle: React.CSSProperties = {
      display: 'flex',
      flexDirection: 'column',
      flex: isExpanded ? sizePercent : 'none',
      minHeight: isExpanded ? 0 : undefined,
      overflow: 'hidden',
    };

    const listItemsStyle: React.CSSProperties = {
      overflowY: 'auto',
      overflowX: 'hidden',
      flex: 1,
      paddingBottom: '12px',
    };

    const listItemStyle: React.CSSProperties = {
      display: 'flex',
      alignItems: 'center',
      padding: '2px 16px 2px 24px',
      fontSize: '13px',
      color: 'var(--vscode-foreground)',
      cursor: 'pointer',
      userSelect: 'none',
      fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
      height: '22px',
      lineHeight: '22px',
    };

    const emptyMessageStyle: React.CSSProperties = {
      padding: '8px 16px 8px 24px',
      fontSize: '12px',
      color: 'var(--vscode-descriptionForeground)',
      fontStyle: 'italic',
      fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
    };

    const resizeHandleStyle: React.CSSProperties = {
      height: '4px',
      cursor: 'ns-resize',
      backgroundColor: 'transparent',
      borderTop: '1px solid var(--vscode-panel-border)',
      transition: 'background-color 0.1s',
    };

    return (
      <>
        <div style={listContainerStyle}>
          <div
            style={sectionHeaderStyle}
            onClick={() => toggleSection(sectionPrefix)}
          >
            <i
              className={`codicon ${isExpanded ? 'codicon-chevron-down' : 'codicon-chevron-right'}`}
              style={chevronStyle}
            />
            <span>{sectionTitle}</span>
          </div>
          {isExpanded && (
            <div style={listItemsStyle}>
              {processes.length > 0 ? (
                (() => {
                  // Blue color cycle for code hash tags (2 shades for better distinction)
                  const blueColors = {
                    dark: [
                      { text: '#7cb7e8', bg: 'rgba(124, 183, 232, 0.15)' },  // Light blue (brightest)
                      { text: '#2d5d9b', bg: 'rgba(45, 93, 155, 0.15)' },    // Deep blue
                    ],
                    light: [
                      { text: '#0078d4', bg: 'rgba(0, 120, 212, 0.1)' },     // Light blue (brightest)
                      { text: '#003d7a', bg: 'rgba(0, 61, 122, 0.1)' },      // Deep blue
                    ],
                  };

                  // Pre-compute color indices based on hash changes
                  let currentColorIndex = 0;
                  const colorIndices: number[] = [];
                  processes.forEach((process, index) => {
                    if (index > 0 && process.version_date !== processes[index - 1].version_date) {
                      currentColorIndex = (currentColorIndex + 1) % 2;
                    }
                    colorIndices.push(currentColorIndex);
                  });

                  return processes.map((process, index) => {
                  const cardId = `${sectionPrefix}-${process.session_id}`;
                  const isHovered = hoveredCards.has(cardId);
                  const hashColorIndex = colorIndices[index];
                  const hashColors = isDarkTheme ? blueColors.dark[hashColorIndex] : blueColors.light[hashColorIndex];

                  // Determine status icon based on process state
                  const getStatusIcon = () => {
                    if (process.status === 'running') {
                      return <i className="codicon codicon-loading codicon-modifier-spin" style={{ marginRight: '8px', fontSize: '16px' }} />;
                    }
                    const result = process.result?.toLowerCase();
                    if (result === 'failed') {
                      return <i className="codicon codicon-error" style={{ marginRight: '8px', fontSize: '16px', color: '#e05252' }} />;
                    }
                    if (result === 'satisfactory') {
                      return <i className="codicon codicon-pass" style={{ marginRight: '8px', fontSize: '16px', color: '#7fc17b' }} />;
                    }
                    return <i className="codicon codicon-circle-outline" style={{ marginRight: '8px', fontSize: '16px', opacity: 0.6 }} />;
                  };

                  return (
                    <div
                      key={process.session_id}
                      style={{
                        ...listItemStyle,
                        backgroundColor: isHovered
                          ? 'var(--vscode-list-hoverBackground)'
                          : 'transparent',
                      }}
                      onClick={() => onCardClick && onCardClick(process)}
                      onMouseEnter={() => handleCardHover(cardId, true)}
                      onMouseLeave={() => handleCardHover(cardId, false)}
                    >
                      {getStatusIcon()}
                      <span style={{
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        flex: 1,
                        minWidth: 0,
                      }}>
                        {process.run_name || 'Untitled'}
                      </span>
                      {process.version_date && (
                        <span style={{
                          fontSize: '10px',
                          fontFamily: 'monospace',
                          color: hashColors.text,
                          backgroundColor: hashColors.bg,
                          padding: '1px 4px',
                          borderRadius: '2px',
                          whiteSpace: 'nowrap',
                          lineHeight: '1',
                          marginRight: '0px',
                        }}>
                          {process.version_date}
                        </span>
                      )}
                    </div>
                  );
                });
                })()
              ) : (
                <div style={emptyMessageStyle}>
                  No {sectionTitle.toLowerCase()}
                </div>
              )}
            </div>
          )}
        </div>
        {showResizeHandle && isExpanded && (
          <div
            style={resizeHandleStyle}
            onMouseDown={(e) => handleMouseDown(sectionPrefix as 'running' | 'finished', e)}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--vscode-focusBorder)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          />
        )}
      </>
    );
  };

  const headerStyle: React.CSSProperties = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderBottom: '1px solid var(--vscode-panel-border)',
    padding: '8px 16px',
    flexShrink: 0,
  };

  const dropdownStyle: React.CSSProperties = {
    position: 'relative',
  };

  const dropdownButtonStyle: React.CSSProperties = {
    padding: '4px 8px',
    fontSize: '12px',
    backgroundColor: 'var(--vscode-dropdown-background)',
    color: 'var(--vscode-dropdown-foreground)',
    border: '1px solid var(--vscode-dropdown-border)',
    borderRadius: '4px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
    fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
  };

  const dropdownMenuStyle: React.CSSProperties = {
    position: 'absolute',
    top: '100%',
    right: 0,
    marginTop: '4px',
    backgroundColor: 'var(--vscode-dropdown-background)',
    border: '1px solid var(--vscode-dropdown-border)',
    borderRadius: '4px',
    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.15)',
    zIndex: 1000,
    minWidth: '100px',
  };

  const dropdownItemStyle: React.CSSProperties = {
    padding: '6px 12px',
    fontSize: '12px',
    color: 'var(--vscode-dropdown-foreground)',
    cursor: 'pointer',
    fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
  };

  const headerTitleStyle: React.CSSProperties = {
    margin: 0,
    fontSize: '14px',
    fontWeight: '600',
    color: 'var(--vscode-editor-foreground)',
  };

  const searchBarContainerStyle: React.CSSProperties = {
    position: 'relative',
    marginBottom: '16px',
  };

  const searchIconStyle: React.CSSProperties = {
    position: 'absolute',
    left: '10px',
    top: '50%',
    transform: 'translateY(-50%)',
    color: isDarkTheme ? '#858585' : '#666666',
    pointerEvents: 'none',
    fontSize: '13px',
  };

  const searchBarInputStyle: React.CSSProperties = {
    width: '100%',
    padding: '5px 10px 5px 28px',
    fontSize: '13px',
    backgroundColor: isDarkTheme ? '#3c3c3c' : '#ffffff',
    color: isDarkTheme ? '#cccccc' : '#333333',
    border: `1px solid ${isDarkTheme ? '#555555' : '#cccccc'}`,
    borderRadius: '4px',
    outline: 'none',
    fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
    boxSizing: 'border-box',
  };

  const renderDropdown = () => (
    <div style={dropdownStyle}>
      <button
        style={dropdownButtonStyle}
        onClick={() => setDropdownOpen(!dropdownOpen)}
      >
        <i className="codicon codicon-database" />
        {currentMode || 'Loading...'}
        <i className={`codicon ${dropdownOpen ? 'codicon-chevron-up' : 'codicon-chevron-down'}`} />
      </button>
      {dropdownOpen && (
        <div style={dropdownMenuStyle}>
          <div
            style={{
              ...dropdownItemStyle,
              backgroundColor: currentMode === 'Local' ? 'var(--vscode-list-activeSelectionBackground)' : 'transparent',
            }}
            onClick={() => handleModeChange('Local')}
          >
            Local
          </div>
          {/* Remote option hidden - feature not yet visible in UI */}
        </div>
      )}
    </div>
  );

  // Show lock screen if in Remote mode without user
  // const showLockScreen = currentMode === 'Remote' && !user;

  return (
    <div style={containerStyle}>
      {showHeader && (
        <div style={headerStyle}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h3 style={headerTitleStyle}>Agent Runs</h3>
            {onRefresh && (
              <button
                onClick={onRefresh}
                style={{
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '4px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--vscode-foreground)',
                  opacity: 0.7,
                  borderRadius: '4px',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.opacity = '1';
                  e.currentTarget.style.backgroundColor = 'var(--vscode-toolbar-hoverBackground)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.opacity = '0.7';
                  e.currentTarget.style.backgroundColor = 'transparent';
                }}
                title="Refresh"
              >
                <i className="codicon codicon-refresh" style={{ fontSize: '14px' }} />
              </button>
            )}
          </div>
          {renderDropdown()}
        </div>
      )}
      {/* Lock screen commented out - auth disabled */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        flex: 1,
        overflow: 'hidden',
      }}>
        {renderExperimentSection(runningProcesses, 'Running', 'running', runningSizePercent, true)}
        {renderExperimentSection(finishedProcesses, 'Finished', 'finished', finishedSizePercent, false)}
      </div>

      {/* Lessons Button */}
      {onLessonsClick && (
        <div
          style={{
            padding: '12px 16px',
            borderTop: `1px solid ${isDarkTheme ? '#3c3c3c' : '#e0e0e0'}`,
            backgroundColor: isDarkTheme ? '#252525' : '#F0F0F0',
          }}
        >
          <button
            onClick={onLessonsClick}
            style={{
              width: '100%',
              padding: '10px 16px',
              backgroundColor: '#43884e',
              color: '#ffffff',
              border: 'none',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: 500,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              transition: 'background-color 0.2s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = '#3a7644';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = '#43884e';
            }}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8.5 1a.5.5 0 0 0-1 0v1.5a.5.5 0 0 0 1 0V1zM3.5 4a.5.5 0 0 0-.5.5v5a.5.5 0 0 0 .5.5h9a.5.5 0 0 0 .5-.5v-5a.5.5 0 0 0-.5-.5h-9zM4 5h8v4H4V5zm8.5 6a.5.5 0 0 1 .5.5v1.5a.5.5 0 0 1-1 0v-1.5a.5.5 0 0 1 .5-.5zm-9 0a.5.5 0 0 1 .5.5v1.5a.5.5 0 0 1-1 0v-1.5a.5.5 0 0 1 .5-.5zM6 13.5a.5.5 0 0 1 .5-.5h3a.5.5 0 0 1 0 1h-3a.5.5 0 0 1-.5-.5z"/>
            </svg>
            Lessons
          </button>
        </div>
      )}
    </div>
  );
};