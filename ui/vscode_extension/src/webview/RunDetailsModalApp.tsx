import React, { useState, useEffect, useCallback, useRef } from 'react';
import { ProcessInfo } from '@sovara/shared-components/types';
import { useIsVsCodeDarkTheme } from '@sovara/shared-components/utils/themeUtils';

declare global {
  interface Window {
    vscode?: {
      postMessage: (message: any) => void;
    };
    isRunDetailsDialog?: boolean;
  }
}

interface OriginalData {
  runName: string;
  result: string;
  notes: string;
}

interface RunDetailsModalProps {
  experiment?: ProcessInfo;
  onClose?: () => void;
  onSave?: (data: OriginalData) => void;
}

export const RunDetailsModalApp: React.FC<RunDetailsModalProps> = ({ experiment: initialExperiment, onClose, onSave }) => {
  const [originalData, setOriginalData] = useState<OriginalData>({ runName: '', result: '', notes: '' });
  const [currentData, setCurrentData] = useState<OriginalData>({ runName: '', result: '', notes: '' });
  const isDarkTheme = useIsVsCodeDarkTheme();

  // Calculate if data has changed
  const hasChanges = Object.keys(originalData).some(
    key => originalData[key as keyof OriginalData] !== currentData[key as keyof OriginalData]
  );

  // Calculate which fields have changed
  const isFieldChanged = (field: keyof OriginalData) => originalData[field] !== currentData[field];

  // Track if we have initialized this
  const hasInitialized = useRef(false);

  useEffect(() => {
    // Only initialize once when component mounts
    if (!hasInitialized.current && initialExperiment) {
      const original = {
        runName: initialExperiment.run_name || '',
        result: initialExperiment.result || '',
        notes: initialExperiment.notes || ''
      };
      setOriginalData(original);
      setCurrentData(original);
      hasInitialized.current = true;
    }
  }, [initialExperiment]);
  
  // Reset the flag when modal closes/reopens
  useEffect(() => {
    return () => {
      hasInitialized.current = false;
    };
  }, []);

  const handleSave = useCallback(() => {
    // Use functional update to get the latest currentData
    setCurrentData((latestCurrentData) => {
      console.log("[RunDetailsModalApp] handleSave with latest data:", latestCurrentData);
      
      // Check for changes using the latest data
      const hasCurrentChanges = Object.keys(originalData).some(
        key => originalData[key as keyof OriginalData] !== latestCurrentData[key as keyof OriginalData]
      );
      
      console.log("[RunDetailsModalApp] hasCurrentChanges:", hasCurrentChanges);
      console.log("[RunDetailsModalApp] originalData:", originalData);
      console.log("[RunDetailsModalApp] latestCurrentData:", latestCurrentData);
      
      if (hasCurrentChanges && onSave) {
        onSave(latestCurrentData);
        console.log("[RunDetailsModalApp] Sent to onSave:", latestCurrentData);
        setOriginalData(latestCurrentData);
      }
      
      return latestCurrentData; // Return unchanged
    });
  }, [originalData, onSave]);
  
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        if (onClose) {
          onClose();
        }
      } else if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        handleSave();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleSave, onClose]);

  const handleReset = () => {
    setCurrentData(originalData);
  };

  const handleFieldChange = (field: keyof OriginalData, value: string) => {
    console.log(`[RunDetailsModalApp] Changing ${field} to:`, value);
    setCurrentData(prev => {
      const newData = { ...prev, [field]: value };
      console.log('[RunDetailsModalApp] New currentData:', newData);
      return newData;
    });
  };

  return (
    <div
      style={{
        margin: 0,
        padding: '20px',
        fontFamily: 'var(--vscode-font-family)',
        fontSize: 'var(--vscode-font-size)',
        color: 'var(--vscode-foreground)',
        background: 'var(--vscode-editor-background)',
      }}
    >
      <div style={{ width: '400px', maxWidth: '100%' }}>
        <h2
          style={{
            margin: '0 0 24px 0',
            fontSize: '16px',
            fontWeight: '600',
            color: 'var(--vscode-editor-foreground)',
          }}
        >
          Edit Run Details
        </h2>

        {/* Run Name Field */}
        <div style={{ marginBottom: '20px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              marginBottom: '8px',
              fontSize: '13px',
              fontWeight: '500',
            }}
          >
            <label htmlFor="runName">Run Name</label>
            {isFieldChanged('runName') && (
              <div
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  backgroundColor: 'var(--vscode-foreground)',
                }}
              />
            )}
          </div>
          <input
            id="runName"
            type="text"
            value={currentData.runName}
            onChange={(e) => handleFieldChange('runName', e.target.value)}
            style={{
              width: '100%',
              maxWidth: '100%',
              minWidth: '0',
              boxSizing: 'border-box',
              padding: '8px 12px',
              border: '1px solid var(--vscode-input-border)',
              borderRadius: '3px',
              background: 'var(--vscode-input-background)',
              color: 'var(--vscode-input-foreground)',
              fontFamily: 'var(--vscode-font-family)',
              fontSize: 'var(--vscode-font-size)',
              outline: 'none',
            }}
            onFocus={(e) => {
              e.target.style.outline = '1px solid var(--vscode-focusBorder)';
              e.target.style.borderColor = 'var(--vscode-focusBorder)';
            }}
            onBlur={(e) => {
              e.target.style.outline = 'none';
              e.target.style.borderColor = 'var(--vscode-input-border)';
            }}
            placeholder="Enter run name..."
          />
        </div>

        {/* Result Field */}
        <div style={{ marginBottom: '20px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              marginBottom: '8px',
              fontSize: '13px',
              fontWeight: '500',
            }}
          >
            <label htmlFor="result">Result</label>
            {isFieldChanged('result') && (
              <div
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  backgroundColor: 'var(--vscode-foreground)',
                }}
              />
            )}
          </div>
          <select
            id="result"
            value={currentData.result}
            onChange={(e) => handleFieldChange('result', e.target.value)}
            style={{
              width: '100%',
              maxWidth: '100%',
              minWidth: '0',
              boxSizing: 'border-box',
              padding: '8px 12px',
              border: '1px solid var(--vscode-input-border)',
              borderRadius: '3px',
              background: 'var(--vscode-input-background)',
              color: 'var(--vscode-input-foreground)',
              fontFamily: 'var(--vscode-font-family)',
              fontSize: 'var(--vscode-font-size)',
              outline: 'none',
            }}
            onFocus={(e) => {
              e.target.style.outline = '1px solid var(--vscode-focusBorder)';
              e.target.style.borderColor = 'var(--vscode-focusBorder)';
            }}
            onBlur={(e) => {
              e.target.style.outline = 'none';
              e.target.style.borderColor = 'var(--vscode-input-border)';
            }}
          >
            <option value="Select a result">Select a result</option>
            <option value="Satisfactory">Satisfactory</option>
            <option value="Failed">Failed</option>
          </select>
        </div>

        {/* Notes Field */}
        <div style={{ marginBottom: '20px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              marginBottom: '8px',
              fontSize: '13px',
              fontWeight: '500',
            }}
          >
            <label htmlFor="notes">Notes</label>
            {isFieldChanged('notes') && (
              <div
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  backgroundColor: 'var(--vscode-foreground)',
                }}
              />
            )}
          </div>
          <textarea
            id="notes"
            value={currentData.notes}
            onChange={(e) => handleFieldChange('notes', e.target.value)}
            rows={3}
            style={{
              width: '100%',
              maxWidth: '100%',
              minWidth: '0',
              boxSizing: 'border-box',
              padding: '8px 12px',
              border: '1px solid var(--vscode-input-border)',
              borderRadius: '3px',
              background: 'var(--vscode-input-background)',
              color: 'var(--vscode-input-foreground)',
              fontFamily: 'var(--vscode-font-family)',
              fontSize: 'var(--vscode-font-size)',
              resize: 'vertical',
              outline: 'none',
              minHeight: '34px',
              maxHeight: '150px',
            }}
            onFocus={(e) => {
              e.target.style.outline = '1px solid var(--vscode-focusBorder)';
              e.target.style.borderColor = 'var(--vscode-focusBorder)';
            }}
            onBlur={(e) => {
              e.target.style.outline = 'none';
              e.target.style.borderColor = 'var(--vscode-input-border)';
            }}
            placeholder="Enter notes..."
          />
        </div>

        {/* Button Group */}
        <div
          style={{
            display: 'flex',
            gap: '12px',
            justifyContent: 'flex-end',
            paddingTop: '20px',
            borderTop: '1px solid var(--vscode-editorWidget-border)',
          }}
        >
          <button
            onClick={handleReset}
            style={{
              padding: '8px 16px',
              border: '1px solid var(--vscode-button-border)',
              borderRadius: '3px',
              cursor: 'pointer',
              fontSize: '12px',
              fontFamily: 'var(--vscode-font-family)',
              background: 'var(--vscode-button-secondaryBackground)',
              color: 'var(--vscode-button-secondaryForeground)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'var(--vscode-button-secondaryHoverBackground)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'var(--vscode-button-secondaryBackground)';
            }}
          >
            Reset
          </button>
          <button
            onClick={handleSave}
            disabled={!hasChanges}
            style={{
              padding: '8px 16px',
              border: `1px solid ${hasChanges ? 'var(--vscode-button-border)' : 'var(--vscode-disabledForeground)'}`,
              borderRadius: '3px',
              cursor: hasChanges ? 'pointer' : 'not-allowed',
              fontSize: '12px',
              fontFamily: 'var(--vscode-font-family)',
              background: hasChanges ? 'var(--vscode-button-background)' : 'var(--vscode-input-background)',
              color: hasChanges ? 'var(--vscode-button-foreground)' : 'var(--vscode-disabledForeground)',
              opacity: hasChanges ? 1 : 0.6,
            }}
            onMouseEnter={(e) => {
              if (hasChanges) {
                e.currentTarget.style.background = 'var(--vscode-button-hoverBackground)';
              }
            }}
            onMouseLeave={(e) => {
              if (hasChanges) {
                e.currentTarget.style.background = 'var(--vscode-button-background)';
              }
            }}
          >
            Save {navigator.platform.toLowerCase().includes('mac') ? '(⌘S)' : '(Ctrl+S)'}
          </button>
        </div>

        {/* Keyboard Hints */}
        <div
          style={{
            fontSize: '11px',
            color: 'var(--vscode-descriptionForeground)',
            marginTop: '16px',
            textAlign: 'center',
          }}
        >
          Press ESC to close • {navigator.platform.toLowerCase().includes('mac') ? '⌘S' : 'Ctrl+S'} to save
        </div>
      </div>
    </div>
  );
};