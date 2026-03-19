import { useEffect, useState, useRef, useCallback } from "react";
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
}


// ============================================================
// Direct ao-playbook HTTP helpers (lesson CRUD bypasses ao-server)
// ============================================================

async function playbookRequest(baseUrl: string, method: string, path: string, apiKey: string, body?: any): Promise<any> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (apiKey) { headers['X-API-Key'] = apiKey; }
  const resp = await fetch(`${baseUrl}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || `HTTP ${resp.status}`);
  }
  const text = await resp.text();
  return text ? JSON.parse(text) : {};
}

/** Parse an SSE mutation response (ao-playbook returns SSE for create/update/delete). */
async function playbookSseMutation(baseUrl: string, method: string, path: string, apiKey: string, body?: any): Promise<any> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'text/event-stream',
  };
  if (apiKey) { headers['X-API-Key'] = apiKey; }
  const resp = await fetch(`${baseUrl}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  // Parse SSE frames to extract result or error event
  let currentEvent = '';
  for (const line of text.split('\n')) {
    if (line.startsWith('event: ')) {
      currentEvent = line.slice(7).trim();
    } else if (line.startsWith('data: ')) {
      const dataStr = line.slice(6);
      try {
        const data = JSON.parse(dataStr);
        if (currentEvent === 'result') { return data; }
        if (currentEvent === 'error') { return { error: data.error || 'Unknown error' }; }
      } catch { /* ignore non-terminal events */ }
      currentEvent = '';
    }
  }
  return { error: 'SSE stream ended unexpectedly' };
}

async function httpGet(path: string): Promise<any> {
  const base = `${window.location.protocol}//${window.location.hostname}:${window.location.port || '4000'}`;
  const resp = await fetch(`${base}${path}`);
  return resp.json();
}

async function httpPost(path: string, body: any = {}): Promise<any> {
  const base = `${window.location.protocol}//${window.location.hostname}:${window.location.port || '4000'}`;
  const resp = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return resp.json();
}

function App() {
  const [experiments, setExperiments] = useState<ProcessInfo[]>([]);
  const [hasMoreFinished, setHasMoreFinished] = useState(false);
  const [selectedExperiment, setSelectedExperiment] = useState<ProcessInfo | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [appliedLessonIds, setAppliedLessonIds] = useState<Set<string>>(new Set());
  const [showDetailsPanel, setShowDetailsPanel] = useState(false);
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
  // ao-playbook direct connection state
  const playbookUrlRef = useRef<string>('');
  const playbookApiKeyRef = useRef<string>('');
  const sseSourceRef = useRef<EventSource | null>(null);

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

  // ============================================================
  // Direct ao-playbook lesson operations
  // ============================================================

  const handleLessonError = useCallback((msg: string) => {
    setIsLessonValidating(false);
    if (msg.toLowerCase().includes('api key') || msg.toLowerCase().includes('invalid') || msg.toLowerCase().includes('unavailable')) {
      setLessonApiKeyError(true);
    } else {
      setLessonError(msg);
      setTimeout(() => setLessonError(null), 5000);
    }
  }, []);

  const fetchFolderDirect = useCallback(async (path: string) => {
    const url = playbookUrlRef.current;
    if (!url) { handleLessonError('Playbook server not configured'); return; }
    try {
      const result = await playbookRequest(url, 'POST', '/api/v1/lessons/folders/ls', playbookApiKeyRef.current, { path });
      if (result.error) { handleLessonError(result.error); return; }
      setLessonFolderResult({
        path: result.path ?? path,
        folders: result.folders || [],
        lessons: result.lessons || [],
        lessonCount: result.lesson_count,
      });
      setLessonApiKeyError(false);
    } catch (e: any) { handleLessonError(e.message); }
  }, [handleLessonError]);

  const refreshExpandedFolders = useCallback(() => {
    for (const p of expandedFoldersRef.current) {
      fetchFolderDirect(p);
    }
  }, [fetchFolderDirect]);

  const handleFetchFolder = useCallback((path: string) => {
    expandedFoldersRef.current.add(path);
    fetchFolderDirect(path);
  }, [fetchFolderDirect]);

  const fetchLessonContent = useCallback(async (id: string) => {
    const url = playbookUrlRef.current;
    if (!url) return;
    try {
      const result = await playbookRequest(url, 'GET', `/api/v1/lessons/${id}`, playbookApiKeyRef.current);
      if (result && !result.error) {
        setLessonContentUpdate({ id: result.id, content: result.content });
      }
    } catch (e: any) { console.error('Failed to fetch lesson content:', e); }
  }, []);

  const fetchAllLessons = useCallback(async () => {
    const url = playbookUrlRef.current;
    if (!url) return;
    try {
      const result = await playbookRequest(url, 'GET', '/api/v1/lessons', playbookApiKeyRef.current);
      const lessons = Array.isArray(result) ? result : result.lessons || [];
      setAllLessons(lessons);
    } catch (e: any) { console.error('Failed to fetch lessons list:', e); }
  }, []);

  // Create webapp MessageSender that routes to HTTP or window events
  const messageSender: MessageSender = {
    send: (message: any) => {
      if (message.type === "showNodeEditModal") {
        window.dispatchEvent(new CustomEvent('show-node-edit-modal', {
          detail: message.payload
        }));
      } else if (message.type === "openNodeEditorTab") {
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
      } else if (message.type === "restart") {
        httpPost('/ui/restart', { session_id: message.session_id });
      } else if (message.type === "erase") {
        httpPost('/ui/erase', { session_id: message.session_id });
      }
    },
  };

  useEffect(() => {
    // Permitir definir la URL del WebSocket por variable de entorno
    const baseWsUrl = import.meta.env.VITE_APP_WS_URL || (() => {
      const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsHost = window.location.hostname === "localhost"
        ? "localhost:4000"
        : window.location.host;
      return `${wsProtocol}//${wsHost}/ws`;
    })();
    
    const socket = new WebSocket(baseWsUrl);
    wsRef.current = socket;

    socket.onopen = () => {
      console.log("Connected to backend");
      // Fetch initial experiment list via HTTP
      httpGet('/ui/experiments').then(msg => {
        if (msg.experiments) {
          setExperiments(msg.experiments as ProcessInfo[]);
          setHasMoreFinished(!!msg.has_more);
        }
      });
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
            const broadcastExperiments = msg.experiments as ProcessInfo[];
            const broadcastIds = new Set(broadcastExperiments.map((e: ProcessInfo) => e.session_id));
            // Merge: use broadcast data for first page, keep previously paginated experiments
            setExperiments(prev => {
              const paginatedExtras = prev.filter(e => !broadcastIds.has(e.session_id));
              return [...broadcastExperiments, ...paginatedExtras];
            });
            setHasMoreFinished(!!(msg as any).has_more);
            // Update selectedExperiment if it matches one in the updated list
            setSelectedExperiment((current) => {
              if (!current) return null;
              const updated = broadcastExperiments.find(
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
                setGraphData(msg.payload ?? null);
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
          // Handle initial connection message with playbook URL
          if ((msg as any).playbook_url) {
            playbookUrlRef.current = (msg as any).playbook_url;
            playbookApiKeyRef.current = (msg as any).playbook_api_key || '';
            // Fetch initial lessons list
            fetchAllLessons();
            // Set up SSE subscription for real-time lesson events
            if (sseSourceRef.current) { sseSourceRef.current.close(); }
            const es = new EventSource(`${(msg as any).playbook_url}/api/v1/events`);
            const onLessonChange = () => { refreshExpandedFolders(); fetchAllLessons(); };
            es.addEventListener('lesson_created', onLessonChange);
            es.addEventListener('lesson_updated', onLessonChange);
            es.addEventListener('lesson_deleted', onLessonChange);
            es.addEventListener('folder_deleted', onLessonChange);
            sseSourceRef.current = es;
          }
          break;

        // Lesson messages are handled directly via ao-playbook HTTP (not WebSocket)

        default:
          console.warn(`Unhandled message type: ${msg.type}`);
      }
    };

    return () => {
      socket.close();
      if (sseSourceRef.current) { sseSourceRef.current.close(); }
    };
  }, []);

  const handleNodeUpdate = (
    nodeId: string,
    field: string,
    value: string,
    sessionId?: string,
    _attachments?: any
  ) => {
    if (!selectedExperiment) return;
    const sid = sessionId || selectedExperiment.session_id;

    if (field === "input") {
      httpPost('/ui/edit-input', { session_id: sid, node_id: nodeId, value });
    } else if (field === "output") {
      httpPost('/ui/edit-output', { session_id: sid, node_id: nodeId, value });
    } else {
      httpPost('/ui/update-node', { session_id: sid, node_id: nodeId, field, value });
    }
  };

  const handleExperimentClick = (experiment: ProcessInfo) => {
    setGraphData(null);
    setAppliedLessonIds(new Set());
    setSelectedExperiment(experiment);
    setShowLessons(false);
    setShowAppliedLessons(false);

    httpGet(`/ui/graph/${experiment.session_id}`).then(msg => {
      if (msg.payload) setGraphData(msg.payload);
    });
    httpGet(`/ui/experiment/${experiment.session_id}`).then(msg => {
      setSelectedExperiment(prev =>
        prev && msg.session_id === prev.session_id
          ? { ...prev, notes: msg.notes, log: msg.log }
          : prev
      );
    });
    httpGet(`/ui/lessons-applied/${experiment.session_id}`).then(msg => {
      const ids = new Set<string>((msg.records || []).map((r: any) => r.lesson_id));
      setAppliedLessonIds(ids);
    });
  };

  const handleLoadMoreFinished = () => {
    httpGet(`/ui/experiments/more?offset=${experiments.length}`).then(msg => {
      if (msg.experiments) {
        setExperiments(prev => {
          const existingIds = new Set(prev.map(p => p.session_id));
          const newExps = (msg.experiments || []).filter(
            (e: ProcessInfo) => !existingIds.has(e.session_id)
          );
          return [...prev, ...newExps];
        });
        setHasMoreFinished(!!msg.has_more);
      }
    });
  };

  const handleLessonsClick = () => {
    setShowLessons(true);
    setSelectedExperiment(null);
    setGraphData(null);

    // Request root folder listing directly from ao-playbook
    fetchFolderDirect('');
  };

  // const running = experiments.filter((e) => e.status === "running");
  // const finished = experiments.filter((e) => e.status === "finished");

  const sortedExperiments = experiments;

  const similarExperiments = sortedExperiments[0];
  const running = sortedExperiments.filter((e) => e.status === "running");
  const finished = sortedExperiments.filter((e) => e.status === "finished");

  return (
    <div className={`app-container ${isDarkTheme ? 'dark' : ''}`}>
      <div className="sidebar" style={{ width: `${sidebarWidth}px` }}>
        <ExperimentsView
          similarProcesses={similarExperiments ? [similarExperiments] : []}
          runningProcesses={running}
          finishedProcesses={finished}
          onCardClick={handleExperimentClick}
          isDarkTheme={isDarkTheme}
          showHeader={true}
          onLessonsClick={handleLessonsClick}
          hasMoreFinished={hasMoreFinished}
          onLoadMoreFinished={handleLoadMoreFinished}
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
            lessons={allLessons.filter((l) => appliedLessonIds.has(l.id))}
            isDarkTheme={isDarkTheme}
            onBack={() => setShowAppliedLessons(false)}
            onFetchLessonContent={fetchLessonContent}
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
            onLessonCreate={async (data: LessonFormData, force?: boolean) => {
              const url = playbookUrlRef.current;
              if (!url) { handleLessonError('Playbook server not configured'); return; }
              setIsLessonValidating(true);
              try {
                const qs = force ? '?force=true' : '';
                const result = await playbookSseMutation(url, 'POST', `/api/v1/lessons${qs}`, playbookApiKeyRef.current, {
                  name: data.name, summary: data.summary, content: data.content, path: data.path || '',
                });
                setIsLessonValidating(false);
                if (result.status === 'rejected') {
                  let reason = result.reason || 'Validation failed';
                  if (result.hint) { reason += `\n\nHint: ${result.hint}`; }
                  setLessonValidationResult({ feedback: reason, severity: 'error', conflicting_lesson_ids: result.conflicting_lesson_ids || [], isRejected: true });
                } else if (result.error) {
                  handleLessonError(result.error);
                } else if (result.status === 'created') {
                  if (result.validation) {
                    setLessonValidationResult({ feedback: result.validation.feedback || '', severity: result.validation.severity || 'info', conflicting_lesson_ids: result.validation.conflicting_lesson_ids || [], isRejected: false });
                  } else { setLessonValidationResult(null); }
                  refreshExpandedFolders();
                }
              } catch (e: any) { handleLessonError(e.message); }
            }}
            onLessonUpdate={async (id: string, data: Partial<LessonFormData>, force?: boolean) => {
              const url = playbookUrlRef.current;
              if (!url) { handleLessonError('Playbook server not configured'); return; }
              setIsLessonValidating(true);
              try {
                const qs = force ? '?force=true' : '';
                const result = await playbookSseMutation(url, 'PUT', `/api/v1/lessons/${id}${qs}`, playbookApiKeyRef.current, data);
                setIsLessonValidating(false);
                if (result.status === 'rejected') {
                  let reason = result.reason || 'Validation failed';
                  if (result.hint) { reason += `\n\nHint: ${result.hint}`; }
                  setLessonValidationResult({ feedback: reason, severity: 'error', conflicting_lesson_ids: result.conflicting_lesson_ids || [], isRejected: true });
                } else if (result.error) {
                  handleLessonError(result.error);
                } else {
                  if (result.validation) {
                    setLessonValidationResult({ feedback: result.validation.feedback || '', severity: result.validation.severity || 'info', conflicting_lesson_ids: result.validation.conflicting_lesson_ids || [], isRejected: false });
                  } else { setLessonValidationResult(null); }
                  refreshExpandedFolders();
                }
              } catch (e: any) { handleLessonError(e.message); }
            }}
            onLessonDelete={async (id: string) => {
              const url = playbookUrlRef.current;
              if (!url) { handleLessonError('Playbook server not configured'); return; }
              try {
                const result = await playbookSseMutation(url, 'DELETE', `/api/v1/lessons/${id}`, playbookApiKeyRef.current);
                if (result.error) { handleLessonError(result.error); }
                else { refreshExpandedFolders(); }
              } catch (e: any) { handleLessonError(e.message); }
            }}
            onNavigateToRun={(sessionId: string, _nodeId?: string) => {
              const experiment = experiments.find(e => e.session_id === sessionId);
              if (experiment) {
                setShowLessons(false);
                setSelectedExperiment(experiment);
                httpGet(`/ui/graph/${sessionId}`).then(msg => {
                  if (msg.payload) setGraphData(msg.payload);
                });
              }
            }}
            onFetchLessonContent={fetchLessonContent}
            onFetchAppliedSessions={async (lessonId: string) => {
              const msg = await httpGet(`/ui/sessions-for-lesson/${lessonId}`);
              return msg.records || [];
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
              lessonsAppliedCount={appliedLessonIds.size}
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