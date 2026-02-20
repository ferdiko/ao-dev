import { useEffect, useState, useRef, useCallback } from "react";
import { LoginScreen } from "./LoginScreen";
import "./App.css";
import type { GraphNode, GraphEdge, ProcessInfo } from "../../../shared_components/types";
import { GraphTabApp } from "../../../shared_components/components/GraphTabApp";
import { ExperimentsView} from "../../../shared_components/components/experiment/ExperimentsView";
import type { MessageSender } from "../../../shared_components/types/MessageSender";
import { LessonsView, type Lesson, type LessonFormData, type ValidationResult } from "../../../shared_components/components/lessons/LessonsView";
import { AppliedLessonsView } from "../../../shared_components/components/lessons/AppliedLessonsView";
import { GraphHeader } from "../../../shared_components/components/graph/GraphHeader";

interface Experiment {
  session_id: string;
  title: string;
  status: string;
  timestamp: string;
}

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

interface WSMessage {
  type: string;
  experiments?: Experiment[];
  payload?: GraphData;
  session_id?: string;
  color_preview? : string[];
  database_mode?: string;
}


function App() {
  // const [authenticated, setAuthenticated] = useState(false);
  // const [user, setUser] = useState<any | null>(null);
  // const [checkingSession, setCheckingSession] = useState(true);
  const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:5958";
  const [experiments, setExperiments] = useState<ProcessInfo[]>([]);
  const [selectedExperiment, setSelectedExperiment] = useState<ProcessInfo | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [showDetailsPanel, setShowDetailsPanel] = useState(false);
  const [databaseMode, setDatabaseMode] = useState<'Local' | 'Remote'>('Local');
  // const [sidebarOpen, setSidebarOpen] = useState(true);
  const [editDialog, setEditDialog] = useState<{
    nodeId: string;
    field: string;
    value: string;
    label: string;
    attachments?: any;
  } | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(250);
  const [isResizing, setIsResizing] = useState(false);
  const graphContainerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const messageBufferRef = useRef<string>(''); // Buffer for incomplete WebSocket frames
  const [showLessons, setShowLessons] = useState(false);
  const [showAppliedLessons, setShowAppliedLessons] = useState(false);
  const [lessonError, setLessonError] = useState<string | null>(null);
  const [lessonValidationResult, setLessonValidationResult] = useState<ValidationResult | null>(null);
  const [isLessonValidating, setIsLessonValidating] = useState(false);
  const [lessonApiKeyError, setLessonApiKeyError] = useState(false);
  const [lessonFolderResult, setLessonFolderResult] = useState<{
    path: string; folders: { path: string; lesson_count: number }[]; lessons: Lesson[]; lessonCount?: number;
  } | null>(null);
  const [lessonContentUpdate, setLessonContentUpdate] = useState<{
    id: string; content: string;
  } | null>(null);
  const expandedFoldersRef = useRef<Set<string>>(new Set(['']));
  const [allLessons, setAllLessons] = useState<Lesson[]>([]);

  // Detect dark theme reactively
  const [isDarkTheme, setIsDarkTheme] = useState(() => {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches || false;
  });

  // Listen for theme changes
  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = (e: MediaQueryListEvent) => {
      setIsDarkTheme(e.matches);
    };

    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  // Handle sidebar resizing
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isResizing) {
        const newWidth = e.clientX;
        // Constrain width between 150px and 600px
        if (newWidth >= 150 && newWidth <= 600) {
          setSidebarWidth(newWidth);
        }
      }
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    if (isResizing) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'ew-resize';
      document.body.style.userSelect = 'none';
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isResizing]);

  const handleResizeStart = () => {
    setIsResizing(true);
  };

  // Create webapp MessageSender that always uses the current WebSocket from the ref
  const messageSender: MessageSender = {
    send: (message: any) => {
      if (message.type === "showNodeEditModal") {
        // Handle showNodeEditModal by dispatching window event (same as VS Code)
        window.dispatchEvent(new CustomEvent('show-node-edit-modal', {
          detail: message.payload
        }));
      } else if (message.type === "openNodeEditorTab") {
        // Handle openNodeEditorTab by dispatching window event to show inline modal
        // This is sent by CustomNode when clicking "Edit input" or "Edit output"
        window.dispatchEvent(new CustomEvent('show-node-edit-modal', {
          detail: {
            nodeId: message.nodeId,
            sessionId: message.sessionId,
            field: message.field,
            label: message.label,
            inputValue: message.inputValue,
            outputValue: message.outputValue,
          }
        }));
      } else if (message.type === "navigateToCode") {
        // Code navigation not available in webapp
      } else if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify(message));
      }
    },
  };

  useEffect(() => {
    // if (!authenticated) return;
    
    // Permitir definir la URL del WebSocket por variable de entorno
    const baseWsUrl = import.meta.env.VITE_APP_WS_URL || (() => {
      const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsHost = window.location.hostname === "localhost"
        ? "localhost:4000"
        : window.location.host;
      return `${wsProtocol}//${wsHost}/ws`;
    })();
    
    // Include user_id in WebSocket URL if available for cleaner handshake authentication
    // const wsUrl = user && user.id ? `${baseWsUrl}?user_id=${encodeURIComponent(user.id)}` : baseWsUrl;

    const socket = new WebSocket(baseWsUrl);
    setWs(socket);
    wsRef.current = socket; // Keep ref in sync

    socket.onopen = () => {
      console.log("Connected to backend");
      // Note: The WebSocket proxy (server.js) automatically sends the handshake
      // with role: "ui" and user_id from the URL query parameter.
      // We should NOT send our own handshake here.

      // Request the experiment list and root folder listing
      socket.send(JSON.stringify({ type: "get_all_experiments" }));
      socket.send(JSON.stringify({ type: "folder_ls", path: "" }));
    };

    socket.onmessage = (event: MessageEvent) => {
      // WebSocket can fragment large messages across multiple frames
      // We need to buffer incomplete JSON until we get a complete message
      const chunk = event.data;

      // Add chunk to buffer
      messageBufferRef.current += chunk;

      // Try to parse the buffered content
      let msg: WSMessage;
      try {
        msg = JSON.parse(messageBufferRef.current);
        // Successfully parsed - clear the buffer and process the message
        messageBufferRef.current = '';
      } catch (error) {
        // JSON is incomplete - wait for more chunks
        return;
      }

      // Process the complete message
      switch (msg.type) {
        case "experiment_list":
          if (msg.experiments) {
            const updatedExperiments = msg.experiments;
            setExperiments(updatedExperiments);
            // Update selectedExperiment if it matches one in the updated list
            // This ensures metadata edits are reflected in the UI
            setSelectedExperiment((current) => {
              if (!current) return null;
              const updated = updatedExperiments.find(
                (exp: ProcessInfo) => exp.session_id === current.session_id
              );
              return updated || current;
            });
          }
          break;

        case "graph_update":
          if (msg.payload) {
            // Only apply graph updates for the currently selected experiment
            setSelectedExperiment((current) => {
              if (current && msg.session_id === current.session_id) {
                setGraphData(msg.payload);
              }
              return current;
            });
          }
          break;

        case "color_preview_update":
          if (msg.session_id) {
            const sid = msg.session_id;
            const color_preview = msg.color_preview;

            setExperiments((prev) => {
              const updated = prev.map(process =>
                process.session_id === sid
                  ? { ...process, color_preview }
                  : process
              );
              return updated;
            });
          }
          break;

        case "session_id":
          // Handle initial connection message with database mode
          if (msg.database_mode) {
            const mode = msg.database_mode === 'local' ? 'Local' : 'Remote';
            setDatabaseMode(mode);
            console.log(`Synchronized database mode to: ${mode}`);
          }
          break;

        case "database_mode_changed":
          // Handle database mode change broadcast from server
          if (msg.database_mode) {
            const mode = msg.database_mode === 'local' ? 'Local' : 'Remote';
            setDatabaseMode(mode);
            console.log(`Database mode changed by another UI to: ${mode}`);
          }
          break;

        case "lessons_list":
          setAllLessons((msg as any).lessons || []);
          break;

        case "folder_ls_result":
          setLessonFolderResult({
            path: (msg as any).path ?? '',
            folders: (msg as any).folders || [],
            lessons: (msg as any).lessons || [],
            lessonCount: (msg as any).lesson_count,
          });
          setLessonApiKeyError(false);
          break;

        case "lessons_refresh":
          // Server signals lessons changed — re-fetch all expanded folders and full list
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: "get_lessons" }));
            for (const p of expandedFoldersRef.current) {
              wsRef.current.send(JSON.stringify({ type: "folder_ls", path: p }));
            }
          }
          break;

        case "lesson_content":
          // Update the specific lesson with its full content
          if ((msg as any).lesson) {
            const lessonWithContent = (msg as any).lesson;
            setLessonContentUpdate({
              id: lessonWithContent.id,
              content: lessonWithContent.content,
            });
          }
          break;

        case "lesson_error":
          console.error('[App] Received lesson_error:', (msg as any).error);
          setIsLessonValidating(false);
          const errorMsg = (msg as any).error || 'An unknown error occurred';
          // Check if it's an API key error
          if (errorMsg.toLowerCase().includes('api key') || errorMsg.toLowerCase().includes('invalid') || errorMsg.toLowerCase().includes('unavailable')) {
            setLessonApiKeyError(true);
          } else {
            setLessonError(errorMsg);
            // Auto-clear error after 5 seconds
            setTimeout(() => setLessonError(null), 5000);
          }
          break;

        case "lesson_created":
        case "lesson_updated":
          console.log(`[App] Received ${msg.type}:`, msg);
          setIsLessonValidating(false);
          if ((msg as any).validation) {
            // Show validation feedback (info or warning)
            setLessonValidationResult({
              feedback: (msg as any).validation.feedback || '',
              severity: (msg as any).validation.severity || 'info',
              conflicting_lesson_ids: (msg as any).validation.conflicting_lesson_ids || [],
              isRejected: false,
            });
          } else {
            // No validation feedback, clear any previous result
            setLessonValidationResult(null);
          }
          break;

        case "lesson_rejected":
          console.log('[App] Received lesson_rejected:', msg);
          setIsLessonValidating(false);
          setLessonValidationResult({
            feedback: (msg as any).reason || 'Validation failed',
            severity: (msg as any).severity || 'error',
            conflicting_lesson_ids: (msg as any).conflicting_lesson_ids || [],
            isRejected: true,
          });
          break;

        default:
          console.warn(`Unhandled message type: ${msg.type}`);
      }
    };

    return () => socket.close();
  }, []);
  // }, [authenticated, user]);

  // On app mount check session (useful after OAuth redirect)
  // Fetch session and set user+authenticated state
  // const checkSession = async () => {
  //   console.log('🔍 checkSession starting, API_BASE:', API_BASE);
  //   setCheckingSession(true);
  //   try {
  //     const sessionUrl = `${API_BASE}/auth/session`;
  //     console.log('📡 Fetching session from:', sessionUrl);
  //     const resp = await fetch(sessionUrl, { credentials: 'include' });
  //     console.log('📡 Session response status:', resp.status, 'ok:', resp.ok);
      
  //     if (!resp.ok) {
  //       console.log('❌ Response not OK, setting authenticated=false');
  //       setAuthenticated(false);
  //       setUser(null);
  //       return;
  //     }
      
  //     const data = await resp.json();
  //     console.log('📋 Session data received:', data);
  //     console.log('📋 Has user?', !!(data && data.user));
      
  //     if (data && data.user) {
  //       console.log('✅ Setting authenticated=true, user:', data.user);
  //       setAuthenticated(true);
  //       setUser(data.user);
  //     } else {
  //       console.log('❌ No user in data, setting authenticated=false');
  //       setAuthenticated(false);
  //       setUser(null);
  //     }
  //   } catch (err) {
  //     console.error('❌ Failed to check session', err);
  //     setAuthenticated(false);
  //     setUser(null);
  //   } finally {
  //     console.log('🏁 checkSession finished, calling setCheckingSession(false)');
  //     setCheckingSession(false);
  //   }
  // };

  // useEffect(() => {
  //   checkSession();
  // }, []);

  const handleNodeUpdate = (
    nodeId: string,
    field: string,
    value: string,
    sessionId?: string,
    attachments?: any
  ) => {
    if (selectedExperiment && ws) {
      const currentSessionId = sessionId || selectedExperiment.session_id;
      const baseMsg = {
        session_id: currentSessionId,
        node_id: nodeId,
        value,
        ...(attachments && { attachments }),
      };

      if (field === "input") {
        ws.send(JSON.stringify({ type: "edit_input", ...baseMsg }));
      } else if (field === "output") {
        ws.send(JSON.stringify({ type: "edit_output", ...baseMsg }));
      } else {
        ws.send(
          JSON.stringify({
            type: "updateNode",
            session_id: currentSessionId,
            nodeId,
            field,
            value,
            ...(attachments && { attachments }),
          })
        );
      }
    }
  };

  const handleExperimentClick = (experiment: ProcessInfo) => {
    // Clear graph data when switching experiments to avoid showing stale data
    setGraphData(null);
    setSelectedExperiment(experiment);
    setShowLessons(false);
    setShowAppliedLessons(false);

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "get_graph", session_id: experiment.session_id }));
      ws.send(JSON.stringify({ type: "get_lessons" }));
    }
  };

  const handleLessonsClick = () => {
    setShowLessons(true);
    setSelectedExperiment(null);
    setGraphData(null);

    // Request root folder listing
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "folder_ls", path: "" }));
    }
  };

  const handleFetchFolder = useCallback((path: string) => {
    expandedFoldersRef.current.add(path);
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "folder_ls", path }));
    }
  }, []);

  const handleDatabaseModeChange = (mode: 'Local' | 'Remote') => {
    // Update local state immediately for responsive UI
    setDatabaseMode(mode);
    
    // Send WebSocket message to server
    if (ws) {
      ws.send(JSON.stringify({
        type: 'set_database_mode',
        mode: mode.toLowerCase()
      }));
    }
  };

  // const running = experiments.filter((e) => e.status === "running");
  // const finished = experiments.filter((e) => e.status === "finished");

  const sortedExperiments = experiments;

  const similarExperiments = sortedExperiments[0];
  const running = sortedExperiments.filter((e) => e.status === "running");
  const finished = sortedExperiments.filter((e) => e.status === "finished");

  // if (checkingSession) {
  //   // while we verify session do not show the login screen to avoid flicker
  //   return (
  //     <div className={`app-container ${isDarkTheme ? 'dark' : ''}`}>
  //       <div style={{ padding: 24 }}>
  //         Checking authentication...
  //       </div>
  //     </div>
  //   );
  // }

  // if (!authenticated) {
  //   return (
  //     <LoginScreen
  //       onSuccess={async () => {
  //         setAuthenticated(true);
  //         // after successful login try to load session user
  //         await checkSession();
  //       }}
  //     />
  //   );
  // }

  return (
    <div className={`app-container ${isDarkTheme ? 'dark' : ''}`}>
      <div className="sidebar" style={{ width: `${sidebarWidth}px` }}>
        <ExperimentsView
          similarProcesses={similarExperiments ? [similarExperiments] : []}
          runningProcesses={running}
          finishedProcesses={finished}
          onCardClick={handleExperimentClick}
          isDarkTheme={isDarkTheme}
          // user={{
          //   displayName: user?.name || user?.displayName,
          //   avatarUrl: user?.picture || user?.avatarUrl,
          //   email: user?.email,
          // }}
          // onLogout={() => {
          //   fetch(`${API_BASE}/auth/logout`, { method: 'POST', credentials: 'include' })
          //     .catch((err) => console.warn('Logout request failed', err));
          //   setAuthenticated(false);
          //   setUser(null);
          // }}
          showHeader={true}
          onModeChange={handleDatabaseModeChange}
          currentMode={databaseMode}
          onLessonsClick={handleLessonsClick}
        />
        <div
          className="sidebar-resize-handle"
          onMouseDown={handleResizeStart}
        />
      </div>

      <div className="graph-container" ref={graphContainerRef}>
        {/* Lesson Error Banner */}
        {lessonError && (
          <div
            style={{
              padding: '10px 16px',
              backgroundColor: isDarkTheme ? '#5a1d1d' : '#ffebee',
              color: isDarkTheme ? '#f48771' : '#d32f2f',
              fontSize: '13px',
              borderBottom: `1px solid ${isDarkTheme ? '#6a2a2a' : '#ffcdd2'}`,
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <span style={{ fontWeight: 500 }}>Error:</span>
            <span>{lessonError}</span>
            <button
              onClick={() => setLessonError(null)}
              style={{
                marginLeft: 'auto',
                background: 'transparent',
                border: 'none',
                color: 'inherit',
                cursor: 'pointer',
                padding: '4px',
                fontSize: '16px',
                lineHeight: 1,
              }}
            >
              ×
            </button>
          </div>
        )}
        {showAppliedLessons && selectedExperiment ? (
          <AppliedLessonsView
            lessons={allLessons.filter((l) =>
              l.appliedTo?.some((a) => a.sessionId === selectedExperiment.session_id)
            )}
            isDarkTheme={isDarkTheme}
            onBack={() => setShowAppliedLessons(false)}
            onFetchLessonContent={(id: string) => {
              if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "get_lesson", lesson_id: id }));
              }
            }}
            lessonContentUpdate={lessonContentUpdate}
          />
        ) : showLessons ? (
          <LessonsView
            isDarkTheme={isDarkTheme}
            validationResult={lessonValidationResult}
            isValidating={isLessonValidating}
            onClearValidation={() => setLessonValidationResult(null)}
            apiKeyError={lessonApiKeyError}
            folderResult={lessonFolderResult}
            lessonContentUpdate={lessonContentUpdate}
            onFetchFolder={handleFetchFolder}
            onLessonCreate={(data: LessonFormData, force?: boolean) => {
              // Create lesson via WebSocket (proxied to ao-playbook)
              if (ws && ws.readyState === WebSocket.OPEN) {
                setIsLessonValidating(true);
                ws.send(JSON.stringify({
                  type: "add_lesson",
                  name: data.name,
                  summary: data.summary,
                  content: data.content,
                  path: data.path || '',
                  force: force || false,
                }));
              }
            }}
            onLessonUpdate={(id: string, data: Partial<LessonFormData>, force?: boolean) => {
              // Update lesson via WebSocket (proxied to ao-playbook)
              if (ws && ws.readyState === WebSocket.OPEN) {
                setIsLessonValidating(true);
                ws.send(JSON.stringify({
                  type: "update_lesson",
                  lesson_id: id,
                  ...data,
                  force: force || false,
                }));
              }
            }}
            onLessonDelete={(id: string) => {
              // Delete lesson via WebSocket (proxied to ao-playbook)
              if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                  type: "delete_lesson",
                  lesson_id: id,
                }));
              }
            }}
            onNavigateToRun={(sessionId: string, nodeId?: string) => {
              // Navigate to the run (and optionally focus on a specific node)
              const experiment = experiments.find(e => e.session_id === sessionId);
              if (experiment) {
                setShowLessons(false);
                setSelectedExperiment(experiment);
                if (ws && ws.readyState === WebSocket.OPEN) {
                  ws.send(JSON.stringify({ type: "get_graph", session_id: sessionId }));
                }
              }
            }}
            onFetchLessonContent={(id: string) => {
              // Fetch individual lesson content via WebSocket
              if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "get_lesson", lesson_id: id }));
              }
            }}
          />
        ) : selectedExperiment && graphData ? (
          <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "auto", position: "relative" }}>
            {/* Graph Header with Lesson Stats */}
            <GraphHeader
              runName={selectedExperiment.run_name || ''}
              isDarkTheme={isDarkTheme}
              sessionId={selectedExperiment.session_id}
              lessons={allLessons}
              onNavigateToLessons={() => setShowLessons(true)}
              onNavigateToAppliedLessons={() => setShowAppliedLessons(true)}
            />
            {/* Graph */}
            <div style={{ flex: 1, minHeight: 0 }}>
              <GraphTabApp
                experiment={selectedExperiment}
                graphData={graphData}
                sessionId={selectedExperiment.session_id}
                messageSender={messageSender}
                isDarkTheme={isDarkTheme}
                onNodeUpdate={handleNodeUpdate}
              />
            </div>
          </div>
        ) : (
          <div className="no-graph">
            {selectedExperiment ? "Loading graph..." : "Select an experiment or view lessons"}
          </div>
        )}
      </div>
    </div>
  );
}

export default App;