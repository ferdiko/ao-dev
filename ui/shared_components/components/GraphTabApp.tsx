import React, { useState, useEffect, useCallback } from 'react';
import { GraphView } from './graph/GraphView';
import { GraphData, ProcessInfo } from '../types';
import { MessageSender } from '../types/MessageSender';
import { WorkflowRunDetailsPanel } from './run/WorkflowRunDetailsPanel';
import { NodeEditorView } from './editor/NodeEditorView';
import { DetectedDocument, getFileExtension, getDocumentKey, isPreviewableDocument } from '../utils/documentDetection';
import { stripSovaraPriorsFromValue } from '../utils/priorsDisplay';
import { parse, stringify } from 'lossless-json';
import { saveDocument } from '../utils/documentDownload';
import { DocumentPreviewModal } from './common/DocumentPreviewModal';

interface GraphTabAppProps {
  run: ProcessInfo | null;
  graphData: GraphData | null;
  runId: string | null;
  messageSender: MessageSender;
  isDarkTheme: boolean;
  onNodeUpdate: (nodeId: string, field: string, value: string, runId?: string, attachments?: any) => void;
  headerContent?: React.ReactNode;
}

export const GraphTabApp: React.FC<GraphTabAppProps> = ({
  run,
  graphData,
  runId,
  messageSender,
  isDarkTheme,
  onNodeUpdate,
  headerContent,
}) => {
  const [showNodeEditModal, setShowNodeEditModal] = useState(false);
  const [nodeEditData, setNodeEditData] = useState<{
    nodeId: string;
    label: string;
    runId: string;
  } | null>(null);

  // State for NodeEditorView
  const [activeTab, setActiveTab] = useState<'input' | 'output'>('input');
  const [inputData, setInputData] = useState<any>(null);
  const [outputData, setOutputData] = useState<any>(null);
  const [originalInputData, setOriginalInputData] = useState<any>(null);
  const [originalOutputData, setOriginalOutputData] = useState<any>(null);
  const [previewDoc, setPreviewDoc] = useState<DetectedDocument | null>(null);

  // Check if there are unsaved changes
  const hasUnsavedChanges =
    stringify(inputData) !== stringify(originalInputData) ||
    stringify(outputData) !== stringify(originalOutputData);

  // Listen for showNodeEditModal messages from messageSender
  useEffect(() => {
    const handleShowNodeEditModal = (event: CustomEvent) => {
      const { nodeId, field, label, inputValue, outputValue, runId: eventSessionId } = event.detail;

      // Parse the JSON values
      let parsedInput = null;
      let parsedOutput = null;

      try {
        if (inputValue) {
          const parsed = parse(inputValue);
          parsedInput = stripSovaraPriorsFromValue((parsed as any)?.to_show ?? parsed);
        }
      } catch (e) {
        parsedInput = inputValue;
      }

      try {
        if (outputValue) {
          const parsed = parse(outputValue);
          parsedOutput = (parsed as any)?.to_show ?? parsed;
        }
      } catch (e) {
        parsedOutput = outputValue;
      }

      setNodeEditData({ nodeId, label, runId: eventSessionId || runId || '' });
      setInputData(parsedInput);
      setOutputData(parsedOutput);
      setOriginalInputData(parsedInput);
      setOriginalOutputData(parsedOutput);
      setActiveTab(field || 'input');
      setShowNodeEditModal(true);
    };

    window.addEventListener('show-node-edit-modal', handleShowNodeEditModal as EventListener);

    return () => {
      window.removeEventListener('show-node-edit-modal', handleShowNodeEditModal as EventListener);
    };
  }, [runId]);

  // Prevent background scrolling when modal is open
  useEffect(() => {
    if (showNodeEditModal) {
      // Prevent scroll on body - keep it hidden
      document.body.style.overflow = 'hidden';
    } else {
      // Restore scroll when modal is closed
      // The CSS has body { overflow: hidden }, so we need to explicitly override it
      // Setting to empty string would just reveal the CSS rule
      document.body.style.overflow = 'auto';
    }

    return () => {
      // Always cleanup on unmount - restore to auto
      document.body.style.overflow = 'auto';
    };
  }, [showNodeEditModal]);

  // Handle opening base64-encoded documents (PDF, images, etc.)
  const handleOpenDocument = useCallback((doc: DetectedDocument) => {
    if (isPreviewableDocument(doc)) {
      setPreviewDoc(doc);
      return;
    }

    // Check if we're in VS Code environment
    if ((window as any).vscode) {
      (window as any).vscode.postMessage({
        type: 'openDocument',
        payload: {
          data: doc.data,
          fileType: getFileExtension(doc.type),
          mimeType: doc.mimeType,
          documentKey: getDocumentKey(doc.data),
          fileName: doc.name,
        },
      });
    } else {
      void saveDocument(doc);
    }
  }, []);

  const handleDownloadDocument = useCallback((doc: DetectedDocument) => {
    if ((window as any).vscode) {
      (window as any).vscode.postMessage({
        type: 'saveDocument',
        payload: {
          data: doc.data,
          fileType: getFileExtension(doc.type),
          mimeType: doc.mimeType,
          fileName: doc.name,
        },
      });
      return;
    }

    void saveDocument(doc);
  }, []);

  if (!run || !runId) {
    return (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: isDarkTheme ? "#252525" : "#F0F0F0",
          color: isDarkTheme ? "#FFFFFF" : "#000000"
        }}
      >
        {/* Empty state - could add a message here if needed */}
      </div>
    );
  }

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "row",
        background: isDarkTheme ? "#252525" : "#F0F0F0",
      }}
    >
      {/* Graph View */}
      {graphData && (
        <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
          <div style={{ width: "100%", height: "100%" }}>
            <GraphView
              nodes={graphData.nodes || []}
              edges={graphData.edges || []}
              onNodeUpdate={(nodeId, field, value) => {
                const nodes = graphData.nodes || [];
                const node = nodes.find((n: any) => n.id === nodeId);
                const attachments = node?.attachments || undefined;
                onNodeUpdate(nodeId, field, value, runId, attachments);
              }}
              run_id={runId}
              messageSender={messageSender}
              isDarkTheme={isDarkTheme}
              metadataPanel={run ? (
                <WorkflowRunDetailsPanel
                  runName={run.name || ''}
                  result={run.result || ''}
                  notes={run.notes || ''}
                  log={run.log || ''}
                  codeVersion={run.version_date || ''}
                  runId={runId || ''}
                  isDarkTheme={isDarkTheme}
                  messageSender={messageSender}
                />
              ) : undefined}
              headerContent={headerContent}
              currentResult={run?.result || ''}
              onResultChange={(result) => {
                messageSender.send({
                  type: 'update_result',
                  run_id: runId,
                  result: result,
                });
              }}
            />
          </div>
        </div>
      )}

      {/* Node Edit Modal */}
      {showNodeEditModal && nodeEditData && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10001,
          }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) {
              setShowNodeEditModal(false);
            }
          }}
          onWheel={(e) => {
            // Prevent scroll events from propagating to background
            e.stopPropagation();
          }}
        >
          <div
            style={{
              backgroundColor: isDarkTheme ? '#1e1e1e' : '#ffffff',
              border: `1px solid ${isDarkTheme ? '#3c3c3c' : '#e0e0e0'}`,
              borderRadius: '6px',
              width: '700px',
              height: '600px',
              minWidth: '400px',
              minHeight: '300px',
              maxWidth: '90vw',
              maxHeight: '90vh',
              resize: 'both',
              overflow: 'hidden',
              boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <NodeEditorView
              inputData={inputData}
              outputData={outputData}
              activeTab={activeTab}
              hasUnsavedChanges={hasUnsavedChanges}
              isDarkTheme={isDarkTheme}
              nodeLabel={nodeEditData.label}
              onTabChange={setActiveTab}
              onInputChange={setInputData}
              onOutputChange={setOutputData}
              onSave={() => {
                const nodes = graphData?.nodes || [];
                const node = nodes.find((n: any) => n.id === nodeEditData.nodeId);
                const attachments = node?.attachments || undefined;

                // Save input if changed
                if (stringify(inputData) !== stringify(originalInputData)) {
                  const inputToSave = stringify({ to_show: inputData, raw: inputData });
                  onNodeUpdate(nodeEditData.nodeId, 'input', inputToSave || '', nodeEditData.runId, attachments);
                  setOriginalInputData(inputData);
                }

                // Save output if changed
                if (stringify(outputData) !== stringify(originalOutputData)) {
                  const outputToSave = stringify({ to_show: outputData, raw: outputData });
                  onNodeUpdate(nodeEditData.nodeId, 'output', outputToSave || '', nodeEditData.runId, attachments);
                  setOriginalOutputData(outputData);
                }
              }}
              onOpenDocument={handleOpenDocument}
            />
          </div>
        </div>
      )}
      {previewDoc && (
        <DocumentPreviewModal
          doc={previewDoc}
          isDarkTheme={isDarkTheme}
          onClose={() => setPreviewDoc(null)}
          onDownloadDocument={handleDownloadDocument}
        />
      )}
    </div>
  );
};
