import React, { useEffect, useState } from 'react';
import { RunsView } from '@sovara/shared-components/components/run/RunsView';
import { GraphView } from '@sovara/shared-components/components/graph/GraphView';
import { WorkflowRunDetailsPanel } from '@sovara/shared-components/components/run/WorkflowRunDetailsPanel';
import { GraphNode, GraphEdge, GraphData, ProcessInfo } from '@sovara/shared-components/types';
import { MessageSender } from '@sovara/shared-components/types/MessageSender';
import { useIsVsCodeDarkTheme } from '@sovara/shared-components/utils/themeUtils';

// Add global type augmentation for window.vscode
declare global {
  interface Window {
    vscode?: {
      postMessage: (message: any) => void;
    };
  }
}

export const App: React.FC = () => {
  const [processes, setProcesses] = useState<ProcessInfo[]>([]);
  const [hasMoreFinished, setHasMoreFinished] = useState(false);
  const [activeTab, setActiveTab] = useState<'runs' | 'run-graph'>('runs');
  const [selectedRun, setSelectedRun] = useState<ProcessInfo | null>(null);
  const [showDetailsPanel, setShowDetailsPanel] = useState(false);
  const [allGraphs, setAllGraphs] = useState<Record<string, GraphData>>({});
  const isDarkTheme = useIsVsCodeDarkTheme();

  // Listen for backend messages and update state
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const message = event.data;
      switch (message.type) {
        case "run_id":
          break;
        case "configUpdate":
          // Config changed - forward to config bridge
          console.log('Config update received:', message.detail);
          window.dispatchEvent(new CustomEvent('configUpdate', { detail: message.detail }));
          break;
        case "graph_update":
          // Graph updates are now handled by individual graph tabs
          break;
        case "color_preview_update": {
          const sid = message.run_id;
          const color_preview = message.color_preview;
          console.log(`Color preview update for ${sid}:`, color_preview);
          setProcesses((prev) => {
            const updated = prev.map(process =>
              process.run_id === sid
                ? { ...process, color_preview }
                : process
            );
            console.log('Updated processes:', updated);
            return updated;
          });
          break;
        }
        case "updateNode":
          // Node updates are now handled by individual graph tabs
          break;
        case "run_list": {
          console.log('[App] Received run_list:', message.runs);
          const broadcastRuns = message.runs || [];
          const broadcastIds = new Set(broadcastRuns.map((run: ProcessInfo) => run.run_id));
          // Merge: use broadcast data for first page, keep previously paginated runs.
          // The broadcast is authoritative for ALL running runs, so any extras
          // not in the broadcast are necessarily finished.
          setProcesses(prev => {
            const paginatedExtras = prev
              .filter((run: ProcessInfo) => !broadcastIds.has(run.run_id))
              .map((run: ProcessInfo) => run.status === 'running' ? { ...run, status: 'finished' } : run);
            return [...broadcastRuns, ...paginatedExtras];
          });
          setHasMoreFinished(!!message.has_more);
          break;
        }
        case "more_runs":
          setProcesses(prev => {
            const existingIds = new Set(prev.map(p => p.run_id));
            const newRuns = (message.runs || []).filter(
              (run: ProcessInfo) => !existingIds.has(run.run_id)
            );
            return [...prev, ...newRuns];
          });
          setHasMoreFinished(!!message.has_more);
          break;
      }
    };
    window.addEventListener('message', handleMessage);
    // Send ready message to VS Code extension
    if (window.vscode) {
      window.vscode.postMessage({ type: 'ready' });
    }
    return () => {
      window.removeEventListener('message', handleMessage);
    };
  }, []);


  const handleRunCardClick = (process: ProcessInfo) => {
    // Instead of switching tabs in the sidebar, open a new graph tab
    if (window.vscode) {
      window.vscode.postMessage({
        type: 'openGraphTab',
        payload: {
          run: process
        }
      });
    }
  };

  const handleLessonsClick = () => {
    // Open lessons in a separate tab
    if (window.vscode) {
      window.vscode.postMessage({ type: 'openLessonsTab' });
    }
  };

  const handleRefresh = () => {
    // Refresh runs from backend
    if (window.vscode) {
      window.vscode.postMessage({ type: 'requestRunRefresh' });
    }
  };

  const handleLoadMoreFinished = () => {
    if (window.vscode) {
      // Offset is total runs loaded (DB query includes both running and finished)
      window.vscode.postMessage({ type: 'get_more_runs', offset: processes.length });
    }
  };

  const handleNodeUpdate = (nodeId: string, field: string, value: string, runId: string, attachments?: any) => {
    if (window.vscode) {
      const baseMsg = {
        run_id: runId,
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
          type: "update_node",
          ...baseMsg,
          field,
        });
      }
    }
  };

  // Message sender for the Graph components
  const messageSender: MessageSender = {
    send: (message: any) => {
      if (window.vscode) {
        window.vscode.postMessage(message);
      }
    },
  };

  // Use runs in the order sent by server (already sorted by name ascending)
  const sortedProcesses = processes;

  // const similarRuns = sortedProcesses.filter(p => p.status === 'similar');
  const similarRuns = sortedProcesses[0];
  const runningRuns = sortedProcesses.filter(p => p.status === 'running');
  const finishedRuns = sortedProcesses.filter(p => p.status === 'finished');

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: isDarkTheme ? "#252525" : "#F0F0F0",
      }}
    >
      <div
        style={
          showDetailsPanel
            ? {
                flex: 1,
                overflow: "hidden",
                background: isDarkTheme ? "#252525" : "#F0F0F0",
              }
            : { flex: 1, overflow: "hidden" }
        }
      >
        {activeTab === "runs" ? (
          <RunsView
            similarProcesses={similarRuns ? [similarRuns] : []}
            runningProcesses={runningRuns}
            finishedProcesses={finishedRuns}
            onCardClick={handleRunCardClick}
            isDarkTheme={isDarkTheme}
            showHeader={true}
            onLessonsClick={handleLessonsClick}
            onRefresh={handleRefresh}
            hasMoreFinished={hasMoreFinished}
            onLoadMoreFinished={handleLoadMoreFinished}
          />
        ) : activeTab === "run-graph" && selectedRun && !showDetailsPanel ? (
          <GraphView
            nodes={allGraphs[selectedRun.run_id]?.nodes || []}
            edges={allGraphs[selectedRun.run_id]?.edges || []}
            onNodeUpdate={(nodeId, field, value) => {
              const nodes = allGraphs[selectedRun.run_id]?.nodes || [];
              const node = nodes.find((n: any) => n.id === nodeId);
              const attachments = node?.attachments || undefined;
              handleNodeUpdate(
                nodeId,
                field,
                value,
                selectedRun.run_id,
                attachments
              );
            }}
            run_id={selectedRun.run_id}
            run={selectedRun}
            messageSender={messageSender}
            isDarkTheme={isDarkTheme}
          />
        ) : activeTab === "run-graph" && selectedRun && showDetailsPanel ? (
          <WorkflowRunDetailsPanel
            runName={selectedRun.name || ''}
            result={selectedRun.result || ''}
            notes={selectedRun.notes || ''}
            log={selectedRun.log || ''}
            onOpenInTab={() => {}}
            onBack={() => setShowDetailsPanel(false)}
            runId={selectedRun.run_id}
          />
        ) : null}
      </div>
    </div>
  );
};
