import { useEffect, useCallback, useMemo, useState } from "react";
import { Document, Page } from "react-pdf";
import Zoom from "react-medium-image-zoom";
import { saveDocument } from "@sovara/shared-components/utils/documentDownload";
import { detectDocument } from "@sovara/shared-components/utils/documentDetection";
import { isImageMime, isPdfMime, type Attachment } from "../attachmentUtils";

export function DocumentPreviewModal({
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
  const detectedDoc = useMemo(
    () => detectDocument(attachment.data, { mime_type: attachment.mimeType, filename: attachment.name }),
    [attachment.data, attachment.mimeType, attachment.name],
  );

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const handleBackdropClick = useCallback(
    (event: React.MouseEvent) => {
      if (event.target === event.currentTarget) {
        onClose();
      }
    },
    [onClose],
  );

  return (
    <div className="attachment-modal-backdrop" onClick={handleBackdropClick}>
      <div className="attachment-modal">
        <div className="attachment-modal-header">
          <span className="attachment-modal-title">{attachment.name}</span>
          <div className="attachment-modal-actions">
            <button
              className="attachment-modal-download"
              type="button"
              title="Download"
              aria-label="Download"
              onClick={() => {
                void saveDocument(
                  detectedDoc || {
                    data: attachment.data,
                    mimeType: attachment.mimeType,
                    type: "unknown",
                    name: attachment.name,
                  },
                );
              }}
            >
              <svg viewBox="0 0 16 16" aria-hidden="true" className="attachment-modal-download-icon">
                <path
                  d="M8 2.25a.75.75 0 0 1 .75.75v5.19l1.72-1.72a.75.75 0 1 1 1.06 1.06L8.53 10.53a.75.75 0 0 1-1.06 0L4.47 7.53a.75.75 0 0 1 1.06-1.06l1.72 1.72V3A.75.75 0 0 1 8 2.25ZM3.75 12a.75.75 0 0 1 .75.75h7a.75.75 0 0 1 1.5 0v.5a1 1 0 0 1-1 1h-8a1 1 0 0 1-1-1v-.5a.75.75 0 0 1 .75-.75Z"
                  fill="currentColor"
                />
              </svg>
            </button>
            <button className="attachment-modal-close" onClick={onClose}>✕</button>
          </div>
        </div>
        <div className="attachment-modal-body">
          {isImageMime(attachment.mimeType) ? (
            <Zoom>
              <img src={dataUri} alt={attachment.name} className="attachment-modal-img" />
            </Zoom>
          ) : isPdfMime(attachment.mimeType) ? (
            <div className="attachment-modal-pdf">
              <Document file={dataUri} onLoadSuccess={({ numPages: pages }) => setNumPages(pages)}>
                {Array.from({ length: numPages }, (_, index) => (
                  <Page key={index + 1} pageNumber={index + 1} width={700} />
                ))}
              </Document>
            </div>
          ) : (
            <div className="attachment-modal-unsupported">Preview is only available for images and PDFs.</div>
          )}
        </div>
      </div>
    </div>
  );
}
