import React, { useState, useEffect, useRef, useCallback } from 'react';
import { PriorsView, Prior, PriorFormData, ValidationResult } from '@sovara/shared-components/components/priors/PriorsView';
import { useIsVsCodeDarkTheme } from '@sovara/shared-components/utils/themeUtils';

declare global {
  interface Window {
    vscode?: {
      postMessage: (message: any) => void;
    };
    isPriorsView?: boolean;
  }
}

export const PriorsTabApp: React.FC = () => {
  const [error, setError] = useState<string | null>(null);
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [serverUnavailable, setServerUnavailable] = useState(false);
  const isDarkTheme = useIsVsCodeDarkTheme();

  // Folder tree data passed to PriorsView via folderResult prop
  const [folderResult, setFolderResult] = useState<{
    path: string; folders: { path: string; prior_count: number }[]; priors: Prior[]; priorCount?: number;
  } | null>(null);
  const [priorContentUpdate, setPriorContentUpdate] = useState<{
    id: string; content: string;
  } | null>(null);
  const pendingAppliedResolvers = useRef<Map<string, (runs: any[]) => void>>(new Map());
  const errorTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Track expanded folders so we can re-fetch them on priors_refresh
  const expandedFoldersRef = useRef<Set<string>>(new Set(['']));

  const fetchFolder = useCallback((path: string) => {
    // Track which folders are expanded
    expandedFoldersRef.current.add(path);
    if (window.vscode) {
      window.vscode.postMessage({ type: 'folder_ls', path });
    }
  }, []);

  const refreshExpandedFolders = useCallback(() => {
    for (const path of expandedFoldersRef.current) {
      if (window.vscode) {
        window.vscode.postMessage({ type: 'folder_ls', path });
      }
    }
  }, []);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const message = event.data;

      switch (message.type) {
        case 'folder_ls_result':
          if (errorTimeoutRef.current) {
            clearTimeout(errorTimeoutRef.current);
            errorTimeoutRef.current = null;
          }
          setFolderResult({
            path: message.path ?? '',
            folders: message.folders || [],
            priors: message.priors || [],
            priorCount: message.prior_count,
          });
          setError(null);
          setServerUnavailable(false);
          break;
        case 'priors_refresh':
          // Server signals that priors changed — re-fetch all expanded folders
          refreshExpandedFolders();
          break;
        case 'prior_content':
          // Update the specific prior with its full content
          console.log('[PriorsTabApp] Received prior_content:', message.prior);
          if (message.prior) {
            setPriorContentUpdate({
              id: message.prior.id,
              content: message.prior.content,
            });
          }
          break;
        case 'runs_for_prior':
          if (message.prior_id) {
            const resolve = pendingAppliedResolvers.current.get(message.prior_id);
            if (resolve) {
              resolve(message.records || []);
              pendingAppliedResolvers.current.delete(message.prior_id);
            }
          }
          break;
        case 'prior_error':
          console.error('[PriorsTabApp] Received prior_error:', message.error);
          setIsValidating(false);
          const errorMsg = message.error || 'An unknown error occurred';
          const normalizedError = errorMsg.toLowerCase();
          const isConnectivityError =
            normalizedError.includes('connect')
            || normalizedError.includes('connection failed')
            || normalizedError.includes('python server not configured')
            || normalizedError.includes('refused')
            || normalizedError.includes('timeout')
            || normalizedError.includes('unavailable');
          const isScopeError =
            normalizedError.includes('no project configured')
            || normalizedError.includes('no user configured');

          if (errorTimeoutRef.current) {
            clearTimeout(errorTimeoutRef.current);
            errorTimeoutRef.current = null;
          }

          if (
            isConnectivityError
          ) {
            setServerUnavailable(true);
            setError(null);
          } else {
            setServerUnavailable(false);
            setError(errorMsg);
            if (!isScopeError) {
              errorTimeoutRef.current = setTimeout(() => {
                setError(null);
                errorTimeoutRef.current = null;
              }, 5000);
            }
          }
          break;
        case 'prior_created':
        case 'prior_updated':
          console.log(`[PriorsTabApp] Received ${message.type}:`, message);
          setIsValidating(false);
          setServerUnavailable(false);
          if (message.validation) {
            // Show validation feedback (info or warning)
            setValidationResult({
              feedback: message.validation.feedback || '',
              severity: message.validation.severity || 'info',
              conflicting_prior_ids: message.validation.conflicting_prior_ids || [],
              isRejected: false,
            });
          } else {
            // No validation feedback, clear any previous result
            setValidationResult(null);
          }
          break;
        case 'prior_rejected':
          console.log('[PriorsTabApp] Received prior_rejected:', message);
          setIsValidating(false);
          setValidationResult({
            feedback: message.reason || 'Validation failed',
            severity: message.severity || 'error',
            conflicting_prior_ids: message.conflicting_prior_ids || [],
            isRejected: true,
          });
          break;
      }
    };

    window.addEventListener('message', handleMessage);

    // Send ready message — request root folder instead of full prior list
    if (window.vscode) {
      window.vscode.postMessage({ type: 'ready' });
    }

    return () => {
      window.removeEventListener('message', handleMessage);
      if (errorTimeoutRef.current) {
        clearTimeout(errorTimeoutRef.current);
        errorTimeoutRef.current = null;
      }
    };
  }, [refreshExpandedFolders]);

  return (
    <div
      style={{
        width: '100%',
        height: '100vh',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {error && (
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
          <span>{error}</span>
          <button
            onClick={() => setError(null)}
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
      <PriorsView
        isDarkTheme={isDarkTheme}
        validationResult={validationResult}
        isValidating={isValidating}
        onClearValidation={() => setValidationResult(null)}
        serverUnavailable={serverUnavailable}
        loadError={error}
        folderResult={folderResult}
        priorContentUpdate={priorContentUpdate}
        onFetchFolder={fetchFolder}
        onPriorCreate={(data: PriorFormData, force?: boolean) => {
          // Create prior via postMessage to backend (proxied to the priors server)
          if (window.vscode) {
            setIsValidating(true);
            window.vscode.postMessage({
              type: 'add_prior',
              name: data.name,
              summary: data.summary,
              content: data.content,
              path: data.path || '',
              force: force || false,
            });
          }
        }}
        onPriorUpdate={(id: string, data: Partial<PriorFormData>, force?: boolean) => {
          // Update prior via postMessage to backend (proxied to the priors server)
          if (window.vscode) {
            setIsValidating(true);
            window.vscode.postMessage({
              type: 'update_prior',
              prior_id: id,
              ...data,
              force: force || false,
            });
          }
        }}
        onPriorDelete={(id: string) => {
          // Delete prior via postMessage to backend (proxied to the priors server)
          if (window.vscode) {
            window.vscode.postMessage({
              type: 'delete_prior',
              prior_id: id,
            });
          }
        }}
        onNavigateToRun={(runId: string, nodeId?: string) => {
          // Navigate to the run - open graph tab (optionally focus on node)
          if (window.vscode) {
            window.vscode.postMessage({ type: 'navigateToRun', runId, nodeId });
          }
        }}
        onFetchPriorContent={(id: string) => {
          // Fetch individual prior content via postMessage to backend
          if (window.vscode) {
            window.vscode.postMessage({ type: 'get_prior', prior_id: id });
          }
        }}
        onFetchAppliedRuns={(priorId: string) => {
          return new Promise((resolve) => {
            pendingAppliedResolvers.current.set(priorId, resolve);
            if (window.vscode) {
              window.vscode.postMessage({ type: 'get_runs_for_prior', prior_id: priorId });
            }
          });
        }}
      />
    </div>
  );
};
