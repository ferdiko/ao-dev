import React, { useEffect, useMemo, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { saveDocument } from "../../utils/documentDownload";
import { DetectedDocument, isPreviewableDocument } from "../../utils/documentDetection";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

export const DocumentPreviewModal: React.FC<{
  doc: DetectedDocument;
  isDarkTheme: boolean;
  onClose: () => void;
  onDownloadDocument?: (doc: DetectedDocument) => void;
}> = ({ doc, isDarkTheme, onClose, onDownloadDocument }) => {
  const [numPages, setNumPages] = useState(0);
  const dataUri = useMemo(() => `data:${doc.mimeType};base64,${doc.data}`, [doc.data, doc.mimeType]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  if (!isPreviewableDocument(doc)) {
    return null;
  }

  return (
    <div
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0, 0, 0, 0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
        zIndex: 1000,
      }}
    >
      <div
        style={{
          width: "min(1100px, 92vw)",
          height: "min(88vh, 920px)",
          minHeight: 0,
          background: isDarkTheme ? "#1f2428" : "#ffffff",
          color: "var(--vscode-foreground)",
          borderRadius: "12px",
          border: `1px solid ${isDarkTheme ? "rgba(110, 118, 129, 0.3)" : "rgba(110, 118, 129, 0.16)"}`,
          boxShadow: "0 18px 40px rgba(0, 0, 0, 0.28)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 16px",
            borderBottom: `1px solid ${isDarkTheme ? "rgba(110, 118, 129, 0.25)" : "rgba(110, 118, 129, 0.14)"}`,
          }}
        >
          <div
            style={{
              fontSize: "13px",
              fontWeight: 600,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {doc.name || "Document preview"}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <button
              type="button"
              title="Download"
              aria-label="Download"
              onClick={() => {
                if (onDownloadDocument) {
                  onDownloadDocument(doc);
                  return;
                }

                void saveDocument(doc);
              }}
              style={{
                border: `1px solid ${isDarkTheme ? "rgba(110, 118, 129, 0.3)" : "rgba(110, 118, 129, 0.2)"}`,
                background: isDarkTheme ? "#171b20" : "#f8fafc",
                color: "var(--vscode-foreground)",
                borderRadius: "8px",
                width: "32px",
                height: "32px",
                padding: 0,
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <svg viewBox="0 0 16 16" aria-hidden="true" style={{ width: "14px", height: "14px", display: "block" }}>
                <path
                  d="M8 2.25a.75.75 0 0 1 .75.75v5.19l1.72-1.72a.75.75 0 1 1 1.06 1.06L8.53 10.53a.75.75 0 0 1-1.06 0L4.47 7.53a.75.75 0 0 1 1.06-1.06l1.72 1.72V3A.75.75 0 0 1 8 2.25ZM3.75 12a.75.75 0 0 1 .75.75h7a.75.75 0 0 1 1.5 0v.5a1 1 0 0 1-1 1h-8a1 1 0 0 1-1-1v-.5a.75.75 0 0 1 .75-.75Z"
                  fill="currentColor"
                />
              </svg>
            </button>
            <button
              onClick={onClose}
              style={{
                border: "none",
                background: "transparent",
                color: "var(--vscode-descriptionForeground)",
                cursor: "pointer",
                fontSize: "18px",
                lineHeight: 1,
                padding: "2px 6px",
                borderRadius: "6px",
              }}
            >
              ×
            </button>
          </div>
        </div>
        <div
          style={{
            flex: 1,
            minHeight: 0,
            background: isDarkTheme ? "#13171b" : "#f4f6f8",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: doc.type === "pdf" ? "flex-start" : "center",
            padding: "12px",
            overflow: "auto",
          }}
        >
          {doc.type === "pdf" ? (
            <div
              style={{
                width: "100%",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: "16px",
                padding: "20px",
                boxSizing: "border-box",
                background: isDarkTheme ? "#2a3138" : "#d7dce2",
                borderRadius: "8px",
              }}
            >
              <Document file={dataUri} onLoadSuccess={({ numPages: pages }) => setNumPages(pages)}>
                {Array.from({ length: numPages }, (_, index) => (
                  <Page
                    key={index + 1}
                    pageNumber={index + 1}
                    width={760}
                    renderTextLayer={false}
                    renderAnnotationLayer={false}
                  />
                ))}
              </Document>
            </div>
          ) : (
            <img
              src={dataUri}
              alt={doc.name || "Image preview"}
              style={{
                maxWidth: "100%",
                maxHeight: "100%",
                objectFit: "contain",
                borderRadius: "8px",
                boxShadow: isDarkTheme ? "0 8px 24px rgba(0, 0, 0, 0.35)" : "0 8px 24px rgba(15, 23, 42, 0.16)",
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
};
