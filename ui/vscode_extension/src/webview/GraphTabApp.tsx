import React, { useState, useEffect, useRef } from 'react';
import { GraphTabApp as SharedGraphTabApp } from '@sovara/shared-components/components/GraphTabApp';
import { GraphData, ProcessInfo } from '@sovara/shared-components/types';
import { MessageSender } from '@sovara/shared-components/types/MessageSender';
import { useIsVsCodeDarkTheme } from '@sovara/shared-components/utils/themeUtils';
import { GraphHeader } from '@sovara/shared-components/components/graph/GraphHeader';
import { Lesson } from '@sovara/shared-components/components/lessons/LessonsView';
import { AppliedLessonsView } from '@sovara/shared-components/components/lessons/AppliedLessonsView';
import { DocumentContextProvider, useDocumentContext } from '@sovara/shared-components/contexts/DocumentContext';

// Global type augmentation for window.vscode
declare global {
  interface Window {
    vscode?: {
      postMessage: (message: any) => void;
    };
    sessionId?: string;
    isGraphTab?: boolean;
  }
}

function normalizeGraphPayload(payload: any): GraphData {
  const nodes = Array.isArray(payload?.nodes)
    ? payload.nodes.map((node: any) => ({
        id: String(node.uuid ?? node.id),
        step_id: typeof node.step_id === 'number' ? node.step_id : undefined,
        input: node.input,
        output: node.output,
        stack_trace: node.stack_trace ?? '',
        label: node.label ?? String(node.uuid ?? node.id ?? ''),
        border_color: node.border_color,
        model: node.model,
        attachments: node.attachments,
      }))
    : [];
  const edges = Array.isArray(payload?.edges)
    ? payload.edges.map((edge: any) => ({
        id: String(edge.id),
        source: String(edge.source_uuid ?? edge.source),
        target: String(edge.target_uuid ?? edge.target),
      }))
    : [];

  return { nodes, edges };
}

// Inner component that uses the document context
const GraphTabAppInner: React.FC = () => {
  const [experiment, setExperiment] = useState<ProcessInfo | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [appliedLessonIds, setAppliedLessonIds] = useState<Set<string>>(new Set());
  const [showAppliedLessons, setShowAppliedLessons] = useState(false);
  const [lessonContentUpdate, setLessonContentUpdate] = useState<{ id: string; content: string } | null>(null);
  const isDarkTheme = useIsVsCodeDarkTheme();
  const { setDocumentOpened } = useDocumentContext();

  // Override body overflow to allow scrolling
  useEffect(() => {
    document.body.style.overflow = 'auto';
    return () => {
      document.body.style.overflow = 'hidden'; // Reset on cleanup
    };
  }, []);

  // Create MessageSender for VS Code environment
  const messageSender: MessageSender = {
    send: (message: any) => {
      if (window.vscode) {
        window.vscode.postMessage(message);
      }
    }
  };

  // Track if we've initialized to avoid re-init on sessionId change (use ref to avoid stale closure)
  const hasInitializedRef = useRef(false);

  // Initialize and listen for messages
  useEffect(() => {
    // Get session ID from window only on first mount (not when sessionId changes)
    if (window.sessionId && !hasInitializedRef.current) {
      setSessionId(window.sessionId);
    }

    const handleMessage = (event: MessageEvent) => {
      const message = event.data;

      switch (message.type) {
        case 'init':
          // Only initialize once - ignore subsequent init messages after user navigation
          if (hasInitializedRef.current) {
            break;
          }
          // Initialize the tab with experiment data
          const initExperiment = message.payload.experiment;
          // Handle transition from title to run_name for backwards compatibility
          const normalizedExperiment = {
            ...initExperiment,
            run_name: initExperiment.run_name || initExperiment.title || '',
          };
          setExperiment(normalizedExperiment);
          setSessionId(message.payload.sessionId);
          hasInitializedRef.current = true;
          break;
        case 'graph_update':
          // Always accept graph updates - the provider already filters by session
          // This avoids stale closure issues when switching experiments
          setGraphData(normalizeGraphPayload(message.payload));
          break;
        case 'configUpdate':
          // Forward config updates to config bridge
          window.dispatchEvent(new CustomEvent('configUpdate', { detail: message.detail }));
          break;
        case 'updateNode':
          // Handle node updates from edit dialogs
          if (message.payload && graphData) {
            const { nodeId, field, value, session_id } = message.payload;
            if (session_id === sessionId) {
              handleNodeUpdate(nodeId, field, value, session_id);
            }
          }
          break;
        case 'experiment_update':
          // Update experiment data if it matches our session
          if (message.session_id === sessionId && message.experiment) {
            setExperiment(message.experiment);
          }
          break;
        case 'experiment_detail':
          // Update experiment with notes/log fetched on demand
          if (message.session_id === sessionId) {
            setExperiment(prev => prev ? { ...prev, notes: message.notes, log: message.log } : prev);
          }
          break;
        case 'experiment_list':
          // Experiment list is handled by the sidebar, not the graph tab
          break;
        case 'vscode-theme-change':
          // Theme changes are handled by the useIsVsCodeDarkTheme hook
          break;
        case 'lessons_list':
          // Update lessons for header stats
          setLessons(message.lessons || []);
          break;
        case 'lessons_applied':
          // Track lesson IDs applied to this session
          if (message.session_id === sessionId) {
            const ids = new Set<string>((message.records || []).map((r: any) => r.lesson_id));
            setAppliedLessonIds(ids);
          }
          break;
        case 'lesson_content':
          // Update lesson content for applied lessons view
          if (message.lesson) {
            setLessonContentUpdate({
              id: message.lesson.id,
              content: message.lesson.content,
            });
          }
          break;
        case 'documentOpened':
          // Track opened document path for UI update
          if (message.payload?.documentKey && message.payload?.path) {
            setDocumentOpened(message.payload.documentKey, message.payload.path);
          }
          break;
      }
    };

    window.addEventListener('message', handleMessage);

    // Send ready message to indicate the webview is loaded
    // Also request lessons data for header stats
    if (window.vscode) {
      window.vscode.postMessage({ type: 'ready' });
      window.vscode.postMessage({ type: 'get_lessons' });
    }

    return () => {
      window.removeEventListener('message', handleMessage);
    };
  }, [sessionId, setDocumentOpened]);

  const handleNodeUpdate = (
    nodeId: string,
    field: string,
    value: string,
    sessionIdParam?: string,
    attachments?: any
  ) => {
    const currentSessionId = sessionIdParam || sessionId;
    if (currentSessionId && window.vscode) {
      const baseMsg = {
        session_id: currentSessionId,
        node_uuid: nodeId,
        value,
        ...(attachments && { attachments }),
      };

      if (field === "input") {
        window.vscode.postMessage({ type: "edit_input", ...baseMsg });
      } else if (field === "output") {
        window.vscode.postMessage({ type: "edit_output", ...baseMsg });
      } else {
        window.vscode.postMessage({
          type: "updateNode",
          session_id: currentSessionId,
          nodeId,
          field,
          value,
          ...(attachments && { attachments }),
        });
      }
    }
  };

  const handleNavigateToLessons = () => {
    // Open lessons tab in VSCode
    if (window.vscode) {
      window.vscode.postMessage({ type: 'openLessonsTab' });
    }
  };

  const handleFetchLessonContent = (id: string) => {
    if (window.vscode) {
      window.vscode.postMessage({ type: 'get_lesson', lesson_id: id });
    }
  };

  const appliedLessons = lessons.filter((l) => appliedLessonIds.has(l.id));

  return (
    <div
      style={{
        width: "100%",
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        background: isDarkTheme ? "#252525" : "#F0F0F0",
        overflow: "auto",
        position: "relative",
      }}
    >
      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
        {showAppliedLessons ? (
          <AppliedLessonsView
            lessons={appliedLessons}
            isDarkTheme={isDarkTheme}
            onBack={() => setShowAppliedLessons(false)}
            onFetchLessonContent={handleFetchLessonContent}
            lessonContentUpdate={lessonContentUpdate}
          />
        ) : (
          <SharedGraphTabApp
            experiment={experiment}
            graphData={graphData}
            sessionId={sessionId}
            messageSender={messageSender}
            isDarkTheme={isDarkTheme}
            onNodeUpdate={handleNodeUpdate}
            headerContent={experiment ? (
              <GraphHeader
                runName={experiment.run_name || ''}
                isDarkTheme={isDarkTheme}
                sessionId={sessionId || undefined}
                lessons={lessons}
                lessonsAppliedCount={appliedLessonIds.size}
                onNavigateToLessons={handleNavigateToLessons}
                onNavigateToAppliedLessons={() => setShowAppliedLessons(true)}
              />
            ) : undefined}
          />
        )}
      </div>
    </div>
  );
};

// Wrap with DocumentContextProvider
export const GraphTabApp: React.FC = () => (
  <DocumentContextProvider>
    <GraphTabAppInner />
  </DocumentContextProvider>
);
