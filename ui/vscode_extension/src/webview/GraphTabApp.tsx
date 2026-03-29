import React, { useState, useEffect, useRef } from 'react';
import { GraphTabApp as SharedGraphTabApp } from '@sovara/shared-components/components/GraphTabApp';
import { GraphData, ProcessInfo } from '@sovara/shared-components/types';
import { MessageSender } from '@sovara/shared-components/types/MessageSender';
import { useIsVsCodeDarkTheme } from '@sovara/shared-components/utils/themeUtils';
import { GraphHeader } from '@sovara/shared-components/components/graph/GraphHeader';
import { Prior } from '@sovara/shared-components/components/priors/PriorsView';
import { AppliedPriorsView } from '@sovara/shared-components/components/priors/AppliedPriorsView';
import { DocumentContextProvider, useDocumentContext } from '@sovara/shared-components/contexts/DocumentContext';

// Global type augmentation for window.vscode
declare global {
  interface Window {
    vscode?: {
      postMessage: (message: any) => void;
    };
    runId?: string;
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
        node_kind: node.node_kind,
        prior_status: node.prior_status,
        prior_count: typeof node.prior_count === 'number' ? node.prior_count : undefined,
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
  const [run, setRun] = useState<ProcessInfo | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [priors, setPriors] = useState<Prior[]>([]);
  const [appliedPriorIds, setAppliedPriorIds] = useState<Set<string>>(new Set());
  const [showAppliedPriors, setShowAppliedPriors] = useState(false);
  const [priorContentUpdate, setPriorContentUpdate] = useState<{ id: string; content: string } | null>(null);
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

  // Track if we've initialized to avoid re-init on runId change (use ref to avoid stale closure)
  const hasInitializedRef = useRef(false);

  // Initialize and listen for messages
  useEffect(() => {
    // Get run ID from window only on first mount (not when runId changes)
    if (window.runId && !hasInitializedRef.current) {
      setRunId(window.runId);
    }

    const handleMessage = (event: MessageEvent) => {
      const message = event.data;

      switch (message.type) {
        case 'init':
          // Only initialize once - ignore subsequent init messages after user navigation
          if (hasInitializedRef.current) {
            break;
          }
          // Initialize the tab with run data
          const initialRun = message.payload.run;
          setRun({ ...initialRun, name: initialRun.name || "" });
          setRunId(message.payload.runId);
          hasInitializedRef.current = true;
          break;
        case 'graph_update':
          // Always accept graph updates - the provider already filters by run
          // This avoids stale closure issues when switching runs
          setGraphData(normalizeGraphPayload(message.payload));
          break;
        case 'configUpdate':
          // Forward config updates to config bridge
          window.dispatchEvent(new CustomEvent('configUpdate', { detail: message.detail }));
          break;
        case 'updateNode':
          // Handle node updates from edit dialogs
          if (message.payload && graphData) {
            const { nodeId, field, value, run_id } = message.payload;
            if (run_id === runId) {
              handleNodeUpdate(nodeId, field, value, run_id);
            }
          }
          break;
        case 'run_update':
          // Update run data if it matches our run
          if (message.run_id === runId && message.run) {
            setRun(message.run);
          }
          break;
        case 'run_detail':
          // Update run with notes/log fetched on demand
          if (message.run_id === runId) {
            setRun(prev => prev ? { ...prev, notes: message.notes, log: message.log } : prev);
          }
          break;
        case 'run_list':
          // Run list is handled by the sidebar, not the graph tab
          break;
        case 'vscode-theme-change':
          // Theme changes are handled by the useIsVsCodeDarkTheme hook
          break;
        case 'priors_list':
          // Update priors for header stats
          setPriors(message.priors || []);
          break;
        case 'priors_applied':
          // Track prior IDs applied to this run
          if (message.run_id === runId) {
            const ids = new Set<string>((message.records || []).map((r: any) => r.prior_id));
            setAppliedPriorIds(ids);
          }
          break;
        case 'prior_content':
          // Update prior content for applied priors view
          if (message.prior) {
            setPriorContentUpdate({
              id: message.prior.id,
              content: message.prior.content,
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
    // Also request priors data for header stats
    if (window.vscode) {
      window.vscode.postMessage({ type: 'ready' });
      window.vscode.postMessage({ type: 'get_priors' });
    }

    return () => {
      window.removeEventListener('message', handleMessage);
    };
  }, [runId, setDocumentOpened]);

  const handleNodeUpdate = (
    nodeId: string,
    field: string,
    value: string,
    sessionIdParam?: string,
    attachments?: any
  ) => {
    const currentRunId = sessionIdParam || runId;
    if (currentRunId && window.vscode) {
      const baseMsg = {
        run_id: currentRunId,
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
          run_id: currentRunId,
          nodeId,
          field,
          value,
          ...(attachments && { attachments }),
        });
      }
    }
  };

  const handleNavigateToPriors = () => {
    // Open priors tab in VSCode
    if (window.vscode) {
      window.vscode.postMessage({ type: 'openPriorsTab' });
    }
  };

  const handleFetchPriorContent = (id: string) => {
    if (window.vscode) {
      window.vscode.postMessage({ type: 'get_prior', prior_id: id });
    }
  };

  const appliedPriors = priors.filter((l) => appliedPriorIds.has(l.id));

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
        {showAppliedPriors ? (
          <AppliedPriorsView
            priors={appliedPriors}
            isDarkTheme={isDarkTheme}
            onBack={() => setShowAppliedPriors(false)}
            onFetchPriorContent={handleFetchPriorContent}
            priorContentUpdate={priorContentUpdate}
          />
        ) : (
          <SharedGraphTabApp
            run={run}
            graphData={graphData}
            runId={runId}
            messageSender={messageSender}
            isDarkTheme={isDarkTheme}
            onNodeUpdate={handleNodeUpdate}
            headerContent={run ? (
              <GraphHeader
                runName={run.name || ''}
                isDarkTheme={isDarkTheme}
                runId={runId || undefined}
                priors={priors}
                priorsAppliedCount={appliedPriorIds.size}
                onNavigateToPriors={handleNavigateToPriors}
                onNavigateToAppliedPriors={() => setShowAppliedPriors(true)}
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
