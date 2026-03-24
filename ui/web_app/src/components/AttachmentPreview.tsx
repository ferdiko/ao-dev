import { useState, useCallback, useEffect, useMemo } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import Zoom from "react-medium-image-zoom";
import "react-medium-image-zoom/dist/styles.css";
import {
  MIME_TO_EXT,
  hasInBrowserPreview,
  isImageMime,
  isPdfMime,
  type Attachment,
} from "../attachmentUtils";

// Configure PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

// ── Download helper ─────────────────────────────────────

/** Trigger a browser download for an attachment. */
function downloadAttachment(att: Attachment) {
  const binary = atob(att.data);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], { type: att.mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = att.name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Thumbnail component ──────────────────────────────────

function AttachmentThumbnail({
  attachment,
  onClick,
}: {
  attachment: Attachment;
  onClick: () => void;
}) {
  const dataUri = `data:${attachment.mimeType};base64,${attachment.data}`;
  const ext = MIME_TO_EXT[attachment.mimeType] ?? attachment.mimeType.split("/")[1]?.toUpperCase() ?? "FILE";

  return (
    <button className="attachment-thumb" onClick={onClick} title={attachment.name}>
      <div className="attachment-thumb-preview">
        {isImageMime(attachment.mimeType) ? (
          <img src={dataUri} alt={attachment.name} className="attachment-thumb-img" />
        ) : isPdfMime(attachment.mimeType) ? (
          <Document file={dataUri} loading={<div className="attachment-thumb-placeholder">PDF</div>}>
            <Page pageNumber={1} width={120} renderTextLayer={false} renderAnnotationLayer={false} />
          </Document>
        ) : (
          <div className="attachment-thumb-placeholder">{ext}</div>
        )}
      </div>
      <div className="attachment-thumb-label">
        <span className="attachment-thumb-ext">{ext}</span>
        <span className="attachment-thumb-name">{attachment.name}</span>
      </div>
    </button>
  );
}

// ── Modal preview (images + PDFs only) ───────────────────

function PreviewModal({
  attachment,
  onClose,
}: {
  attachment: Attachment;
  onClose: () => void;
}) {
  const [numPages, setNumPages] = useState<number>(0);

  const dataUri = useMemo(
    () => `data:${attachment.mimeType};base64,${attachment.data}`,
    [attachment],
  );

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  return (
    <div className="attachment-modal-backdrop" onClick={handleBackdropClick}>
      <div className="attachment-modal">
        <div className="attachment-modal-header">
          <span className="attachment-modal-title">{attachment.name}</span>
          <button className="attachment-modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="attachment-modal-body">
          {isImageMime(attachment.mimeType) ? (
            <Zoom>
              <img src={dataUri} alt={attachment.name} className="attachment-modal-img" />
            </Zoom>
          ) : isPdfMime(attachment.mimeType) ? (
            <div className="attachment-modal-pdf">
              <Document
                file={dataUri}
                onLoadSuccess={({ numPages: n }) => setNumPages(n)}
              >
                {Array.from({ length: numPages }, (_, i) => (
                  <Page key={i + 1} pageNumber={i + 1} width={700} />
                ))}
              </Document>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ── Main AttachmentStrip ─────────────────────────────────

export function AttachmentStrip({ attachments }: { attachments: Attachment[] }) {
  const [previewAtt, setPreviewAtt] = useState<Attachment | null>(null);

  if (attachments.length === 0) return null;

  function handleClick(att: Attachment) {
    if (hasInBrowserPreview(att.mimeType)) {
      setPreviewAtt(att);
    } else {
      // Office docs (DOCX, XLSX, PPTX, etc.): download and let OS open
      downloadAttachment(att);
    }
  }

  return (
    <>
      <div className="attachment-strip">
        {attachments.map((att) => (
          <AttachmentThumbnail
            key={att.id}
            attachment={att}
            onClick={() => handleClick(att)}
          />
        ))}
      </div>
      {previewAtt && (
        <PreviewModal
          attachment={previewAtt}
          onClose={() => setPreviewAtt(null)}
        />
      )}
    </>
  );
}
