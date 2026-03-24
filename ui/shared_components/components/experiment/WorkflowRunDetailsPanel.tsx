import React, { useState, useEffect } from "react";
import { WorkflowRunDetailsPanelProps } from "../../types";
import { useIsVsCodeDarkTheme } from "../../utils/themeUtils";

interface Props extends WorkflowRunDetailsPanelProps {
  onBack?: () => void;
  sessionId?: string;
  isDarkTheme?: boolean;
}

const resultOptions = [
  { value: "", label: "Select a result" },
  { value: "Satisfactory", label: "Satisfactory" },
  { value: "Failed", label: "Failed" }
];

export const WorkflowRunDetailsPanel: React.FC<Props> = ({
  runName = "",
  result = "",
  notes = "",
  log = "",
  codeHash = "",
  onOpenInTab,
  onBack,
  sessionId = "",
  isDarkTheme: isDarkThemeProp,
  messageSender,
}) => {
  const [localRunName, setLocalRunName] = useState(runName);
  const [localResult, setLocalResult] = useState(result);
  const [localNotes, setLocalNotes] = useState(notes);
  const vscodeTheme = useIsVsCodeDarkTheme();
  const isDarkTheme = isDarkThemeProp !== undefined ? isDarkThemeProp : vscodeTheme;

  // Sync local state with props when they change (e.g., new data from database)
  useEffect(() => {
    setLocalRunName(runName);
  }, [runName]);

  useEffect(() => {
    setLocalResult(result);
  }, [result]);

  useEffect(() => {
    setLocalNotes(notes);
  }, [notes]);

  useEffect(() => {
  }, [codeHash]);

  const handleRunNameChange = (value: string) => {
    setLocalRunName(value);
    if (messageSender && sessionId) {
      messageSender.send({
        type: "update_run_name",
        session_id: sessionId,
        run_name: value,
      });
    }
  };

  const handleResultChange = (value: string) => {
    setLocalResult(value);
    if (messageSender && sessionId) {
      messageSender.send({
        type: "update_result",
        session_id: sessionId,
        result: value,
      });
    }
  };

  const handleNotesChange = (value: string) => {
    setLocalNotes(value);
    if (messageSender && sessionId) {
      messageSender.send({
        type: "update_notes",
        session_id: sessionId,
        notes: value,
      });
    }
  };
 
  const containerStyle: React.CSSProperties = {
    padding: "20px 20px 40px 20px",
    boxSizing: "border-box",
    backgroundColor: isDarkTheme ? "#252525" : "#F0F0F0",
    color: isDarkTheme ? "#FFFFFF" : "#000000",
    fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
    };

    const fieldStyle: React.CSSProperties = {
      width: "100%",
      padding: "6px 8px",
      fontSize: "13px",
      fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
      background: isDarkTheme ? "#2d2d2d" : "#ffffff",
      color: isDarkTheme ? "#cccccc" : "#333333",
      border: `1px solid ${isDarkTheme ? "#555555" : "#d0d0d0"}`,
      borderRadius: "2px",
      boxSizing: "border-box",
      marginBottom: "16px",
      outline: "none",
    };

    const selectStyle: React.CSSProperties = {
      ...fieldStyle,
      padding: "6px 32px 6px 8px",
      appearance: "none",
      MozAppearance: "none",
      WebkitAppearance: "none",
      marginBottom: "16px",
    };

    const buttonStyle: React.CSSProperties = {
      ...fieldStyle,
      background: isDarkTheme ? "#0e639c" : "#007acc",
      color: "#ffffff",
      cursor: "pointer",
      fontSize: "13px",
      border: `1px solid ${isDarkTheme ? "#0e639c" : "#007acc"}`,
      transition: "background-color 0.2s",
      fontWeight: "normal",
    };

    const textareaStyle: React.CSSProperties = {
      ...fieldStyle,
      resize: "none",
      minHeight: "80px",
      maxHeight: "150px",
      overflowY: "auto",
      marginBottom: "5px",
    };
    
  return (
    <div style={containerStyle}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          fontWeight: "600",
          fontSize: "16px",
          marginBottom: "24px",
          color: isDarkTheme ? "#ffffff" : "#000000",
        }}
      >
        {onBack && (
          <button
            onClick={onBack}
            style={{
              background: "none",
              border: "none",
              color: isDarkTheme ? "#ffffff" : "#000000",
              fontSize: "16px",
              cursor: "pointer",
              marginRight: "8px",
              lineHeight: 1,
              padding: "4px",
              borderRadius: "2px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
            title="Back"
          >
            ← {/* Unicode left arrow instead of codicon */}
          </button>
        )}
        Workflow run
      </div>
      {/* Title */}
      <label style={{
        fontSize: "13px",
        fontWeight: "600",
        marginBottom: "4px",
        display: "block",
        color: isDarkTheme ? "#cccccc" : "#333333",
      }}>Run name</label>
      <input
        type="text"
        value={localRunName}
        onChange={(e) => handleRunNameChange(e.target.value)}
        style={fieldStyle}
      />

      {/* Result */}
      <label style={{
        fontSize: "13px",
        fontWeight: "600",
        marginBottom: "4px",
        display: "block",
        color: isDarkTheme ? "#cccccc" : "#333333",
      }}>Result</label>
      <div style={{ position: "relative", width: "100%" }}>
        <select
          value={localResult}
          onChange={(e) => handleResultChange(e.target.value)}
          style={selectStyle}
        >
          {resultOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <i
          className="codicon codicon-chevron-down"
          style={{
            position: "absolute",
            right: "12px",
            top: "7px",
            pointerEvents: "none",
            fontSize: "16px",
            color: isDarkTheme ? "#888888" : "#666666",
          }}
        />
      </div>

      {/* Code Hash */}
      <label style={{
        fontSize: "13px",
        fontWeight: "600",
        marginBottom: "4px",
        display: "block",
        color: isDarkTheme ? "#cccccc" : "#333333",
      }}>Code Hash</label>
      <input
        type="text"
        value={codeHash}
        readOnly
        style={{
          ...fieldStyle,
          fontFamily: "monospace",
          cursor: "default",
        }}
      />

      {/* Notes */}
      <label style={{
        fontSize: "13px",
        fontWeight: "600",
        marginBottom: "4px",
        display: "block",
        color: isDarkTheme ? "#cccccc" : "#333333",
      }}>Notes</label>
      <textarea
        value={localNotes}
        onChange={(e) => handleNotesChange(e.target.value)}
        style={textareaStyle}
      />

      {/* Log */}
      <label style={{
        fontSize: "13px",
        fontWeight: "600",
        marginBottom: "4px",
        display: "block",
        color: isDarkTheme ? "#cccccc" : "#333333",
      }}>Log</label>
      <textarea value={log} readOnly style={textareaStyle} />


      {/* Button open in tab */}
      {/* <button
        onClick={() => {
          if (window.vscode) {
            window.vscode.postMessage({
              type: "open_log_tab_side_by_side",
              payload: {
                runName: localRunName,
                result: localResult,
                log,
              },
            });
          }
        }}
        style={buttonStyle}
      >
        Open in tab
      </button> */}
    </div>
  );
};