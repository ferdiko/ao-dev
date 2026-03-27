import React, { useState, useEffect, useCallback } from 'react';
import { NodeEditorView } from '@sovara/shared-components/components/editor/NodeEditorView';
import { DocumentPreviewModal } from '@sovara/shared-components/components/common/DocumentPreviewModal';
import { useIsVsCodeDarkTheme } from '@sovara/shared-components/utils/themeUtils';
import { parse, stringify } from 'lossless-json';
import {
  DetectedDocument,
  getDocumentKey,
  getFileExtension,
  isPreviewableDocument,
} from '@sovara/shared-components/utils/documentDetection';

declare global {
  interface Window {
    vscode?: {
      postMessage: (message: any) => void;
    };
    nodeEditorContext?: {
      nodeId: string;
      runId: string;
      field: 'input' | 'output';
      label: string;
      inputValue: string;
      outputValue: string;
    };
  }
}

/**
 * lossless-json stringify can return undefined.
 * Normalize it to always return a string.
 */
const safeStringify = (
  value: unknown,
  replacer?: Parameters<typeof stringify>[1],
  space?: Parameters<typeof stringify>[2]
): string => {
  return stringify(value, replacer, space) ?? '';
};

/** Parse a JSON string, returning null on failure. */
const extractDisplayData = (jsonStr: string): unknown => {
  try {
    return parse(jsonStr);
  } catch {
    return null;
  }
};

// Initialize from window context immediately (before component mounts)
const getInitialContext = () => {
  return window.nodeEditorContext || null;
};

const getInitialParsedData = (ctx: typeof window.nodeEditorContext, field: 'inputValue' | 'outputValue') => {
  if (!ctx) return null;
  try {
    return extractDisplayData(ctx[field]);
  } catch {
    return null;
  }
};

export const NodeEditorTabApp: React.FC = () => {
  const isDarkTheme = useIsVsCodeDarkTheme();

  // Initialize state directly from window context
  const [context, setContext] = useState(getInitialContext);
  const [inputData, setInputData] = useState(() => getInitialParsedData(window.nodeEditorContext, 'inputValue'));
  const [outputData, setOutputData] = useState(() => getInitialParsedData(window.nodeEditorContext, 'outputValue'));
  const [initialInputData, setInitialInputData] = useState(() => {
    const data = getInitialParsedData(window.nodeEditorContext, 'inputValue');
    return data ? parse(safeStringify(data)) : null;
  });
  const [initialOutputData, setInitialOutputData] = useState(() => {
    const data = getInitialParsedData(window.nodeEditorContext, 'outputValue');
    return data ? parse(safeStringify(data)) : null;
  });
  const [activeTab, setActiveTab] = useState<'input' | 'output'>(() => window.nodeEditorContext?.field || 'input');
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<DetectedDocument | null>(null);

  // Listen for messages from extension
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const message = event.data;

      switch (message.type) {
        case 'init':
        case 'updateNodeData':
          // Initialize or update with new node data
          const data = message.payload || message.data;
          if (data) {
            setContext(data);
            setActiveTab(data.field);

            const input = extractDisplayData(data.inputValue);
            const output = extractDisplayData(data.outputValue);

            setInputData(input);
            setOutputData(output);
            setInitialInputData(parse(safeStringify(input)));
            setInitialOutputData(parse(safeStringify(output)));
            setHasUnsavedChanges(false);
          }
          break;

        case 'saved':
          // Server confirmed save
          setHasUnsavedChanges(false);
          break;
      }
    };

    window.addEventListener('message', handleMessage);

    // Send ready message
    if (window.vscode) {
      window.vscode.postMessage({ type: 'ready' });
    }

    return () => {
      window.removeEventListener('message', handleMessage);
    };
  }, []);

  // Detect changes
  useEffect(() => {
    if (initialInputData === null && initialOutputData === null) {
      setHasUnsavedChanges(false);
      return;
    }

    const inputChanged = safeStringify(inputData) !== safeStringify(initialInputData);
    const outputChanged = safeStringify(outputData) !== safeStringify(initialOutputData);

    setHasUnsavedChanges(inputChanged || outputChanged);
  }, [inputData, outputData, initialInputData, initialOutputData]);

  // Handle save
  const handleSave = useCallback(() => {
    if (!context || !window.vscode) return;

    // Check if input changed
    const inputChanged = safeStringify(inputData) !== safeStringify(initialInputData);
    if (inputChanged) {
      window.vscode.postMessage({
        type: 'edit_input',
        run_id: context.runId,
        node_uuid: context.nodeId,
        value: safeStringify(inputData),
      });
    }

    // Check if output changed
    const outputChanged = safeStringify(outputData) !== safeStringify(initialOutputData);
    if (outputChanged) {
      window.vscode.postMessage({
        type: 'edit_output',
        run_id: context.runId,
        node_uuid: context.nodeId,
        value: safeStringify(outputData),
      });
    }

    // Update initial data to reflect saved state
    setInitialInputData(parse(safeStringify(inputData)));
    setInitialOutputData(parse(safeStringify(outputData)));
    setHasUnsavedChanges(false);

    // Close the tab after saving
    window.vscode.postMessage({ type: 'closeTab' });
  }, [context, inputData, outputData, initialInputData, initialOutputData]);

  // Handle document open
  const handleOpenDocument = useCallback((doc: DetectedDocument) => {
    if (isPreviewableDocument(doc)) {
      setPreviewDoc(doc);
      return;
    }

    if (window.vscode) {
      window.vscode.postMessage({
        type: 'openDocument',
        payload: {
          data: doc.data,
          fileType: getFileExtension(doc.type),
          mimeType: doc.mimeType,
          documentKey: getDocumentKey(doc.data),
          fileName: doc.name,
        },
      });
    }
  }, []);

  const handleDownloadDocument = useCallback((doc: DetectedDocument) => {
    if (!window.vscode) {
      return;
    }

    window.vscode.postMessage({
      type: 'saveDocument',
      payload: {
        data: doc.data,
        fileType: getFileExtension(doc.type),
        mimeType: doc.mimeType,
        fileName: doc.name,
      },
    });
  }, []);

  if (!context) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100vh',
          color: isDarkTheme ? '#cccccc' : '#333333',
          backgroundColor: isDarkTheme ? '#1e1e1e' : '#ffffff',
        }}
      >
        Loading...
      </div>
    );
  }

  return (
    <>
      <NodeEditorView
        inputData={inputData}
        outputData={outputData}
        activeTab={activeTab}
        hasUnsavedChanges={hasUnsavedChanges}
        isDarkTheme={isDarkTheme}
        nodeLabel={context.label}
        onTabChange={setActiveTab}
        onInputChange={setInputData}
        onOutputChange={setOutputData}
        onSave={handleSave}
        onOpenDocument={handleOpenDocument}
      />
      {previewDoc && (
        <DocumentPreviewModal
          doc={previewDoc}
          isDarkTheme={isDarkTheme}
          onClose={() => setPreviewDoc(null)}
          onDownloadDocument={handleDownloadDocument}
        />
      )}
    </>
  );
};
