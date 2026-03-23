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
  const attachments: Attachment[] = [];
  let counter = 0;

  function processDataUri(uri: string, name?: string) {
    const match = uri.match(/^data:([^;]+);base64,(.+)$/s);
    if (match) {
      attachments.push({
        id: `att-${counter++}`,
        name: name ?? `attachment-${counter}`,
        mimeType: match[1],
        data: match[2],
      });
    }
  }

  function scan(obj: unknown, key?: string): void {
    if (typeof obj === "string") {
      if (obj.startsWith("data:") && obj.includes(";base64,")) {
        processDataUri(obj, key);
      }
      return;
    }
    if (Array.isArray(obj)) {
      obj.forEach((item, i) => scan(item, `${key ?? "item"}-${i}`));
      return;
    }
    if (obj && typeof obj === "object") {
      const record = obj as Record<string, unknown>;

      if (
        record.type === "image_url" &&
        record.image_url &&
        typeof (record.image_url as Record<string, unknown>).url === "string"
      ) {
        processDataUri((record.image_url as Record<string, unknown>).url as string, "image");
        return;
      }

      if (typeof record.data === "string" && typeof record.mime_type === "string") {
        const mime = record.mime_type as string;
        if (MIME_TO_EXT[mime]) {
          attachments.push({
            id: `att-${counter++}`,
            name: (record.name as string) ?? `file-${counter}.${mime.split("/")[1]}`,
            mimeType: mime,
            data: record.data as string,
          });
          return;
        }
      }

      for (const [childKey, value] of Object.entries(record)) {
        scan(value, childKey);
      }
    }
  }

  scan(data);
  return attachments;
}
