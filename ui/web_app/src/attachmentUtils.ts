import {
  extractAttachments as extractSharedAttachments,
  type MessageAttachment,
} from "@sovara/shared-components/utils/attachmentExtraction";

export interface Attachment {
  id: string;
  name: string;
  mimeType: string;
  data: string;
}

export const MIME_TO_EXT: Record<string, string> = {
  "application/pdf": "PDF",
  "image/png": "PNG",
  "image/jpeg": "JPEG",
  "image/gif": "GIF",
  "image/webp": "WebP",
  "image/svg+xml": "SVG",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
};

export function hasInBrowserPreview(mime: string): boolean {
  return mime.startsWith("image/") || mime === "application/pdf";
}

export function isImageMime(mime: string): boolean {
  return mime.startsWith("image/");
}

export function isPdfMime(mime: string): boolean {
  return mime === "application/pdf";
}

export function extractAttachments(data: Record<string, unknown>): Attachment[] {
  return extractSharedAttachments(data) as MessageAttachment[];
}
