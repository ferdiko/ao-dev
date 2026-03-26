import { useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import "react-medium-image-zoom/dist/styles.css";
import {
  MIME_TO_EXT,
  hasInBrowserPreview,
  isImageMime,
  isPdfMime,
  type Attachment,
} from "../attachmentUtils";
import { saveDocument } from "@sovara/shared-components/utils/documentDownload";
import { detectDocument } from "@sovara/shared-components/utils/documentDetection";
import { DocumentPreviewModal } from "./DocumentPreviewModal";

// Configure PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

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

// ── Main AttachmentStrip ─────────────────────────────────

export function AttachmentStrip({ attachments }: { attachments: Attachment[] }) {
  const [previewAtt, setPreviewAtt] = useState<Attachment | null>(null);

  if (attachments.length === 0) return null;

  function handleClick(att: Attachment) {
    if (hasInBrowserPreview(att.mimeType)) {
      setPreviewAtt(att);
    } else {
      void saveDocument(
        detectDocument(att.data, { mime_type: att.mimeType, filename: att.name }) || {
          data: att.data,
          mimeType: att.mimeType,
          type: "unknown",
          name: att.name,
        },
      );
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
        <DocumentPreviewModal
          attachment={previewAtt}
          onClose={() => setPreviewAtt(null)}
        />
      )}
    </>
  );
}
