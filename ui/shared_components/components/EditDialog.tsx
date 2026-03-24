import React, { useState, useEffect } from "react";

interface EditDialogProps {
  title: string;
  value: string;
  onSave: (value: string) => void;
  onCancel: () => void;
  isDarkTheme?: boolean;
}

export const EditDialog: React.FC<EditDialogProps> = ({
  title,
  value,
  onSave,
  onCancel,
  isDarkTheme = false,
}) => {
  const [text, setText] = useState(value);

  useEffect(() => {
    setText(value);
  }, [value]);

  const colors = isDarkTheme
    ? {
        background: "#2c2c2c",
        overlay: "rgba(0, 0, 0, 0.6)",
        textareaBg: "#1e1e1e",
        text: "#fff",
        border: "#444",
        cancelBg: "#444",
        saveBg: "#007acc",
      }
    : {
        background: "#fff",
        overlay: "rgba(0, 0, 0, 0.3)",
        textareaBg: "#f8f8f8",
        text: "#000",
        border: "#ccc",
        cancelBg: "#ddd",
        saveBg: "#007acc",
      };

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: colors.overlay,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          onCancel();
        }
      }}
    >
      <div
        style={{
          backgroundColor: colors.background,
          borderRadius: "10px",
          padding: "24px",
          width: "80%",
          maxWidth: "700px",
          maxHeight: "80vh",
          display: "flex",
          flexDirection: "column",
          gap: "16px",
          boxShadow: "0 4px 20px rgba(0,0,0,0.3)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            fontSize: "18px",
            fontWeight: 600,
            color: colors.text,
            textAlign: "left",
          }}
        >
          {title}
        </div>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
          }}
        >
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            style={{
              width: "100%",
              minHeight: "300px",
              padding: "12px",
              backgroundColor: colors.textareaBg,
              color: colors.text,
              border: `1px solid ${colors.border}`,
              borderRadius: "6px",
              resize: "vertical",
              fontFamily: "monospace",
              fontSize: "14px",
              lineHeight: "1.5",
              outline: "none",
              boxSizing: "border-box",
            }}
          />
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: "10px",
            marginTop: "8px",
          }}
        >
          <button
            onClick={onCancel}
            style={{
              padding: "8px 16px",
              backgroundColor: colors.cancelBg,
              color: colors.text,
              border: "none",
              borderRadius: "6px",
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={() => onSave(text)}
            style={{
              padding: "8px 16px",
              backgroundColor: colors.saveBg,
              color: "#fff",
              border: "none",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: 500,
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
};
