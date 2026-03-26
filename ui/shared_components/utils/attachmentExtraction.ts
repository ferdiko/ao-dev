import { detectDocument, getFileExtension } from "./documentDetection";

export interface MessageAttachment {
  id: string;
  name: string;
  mimeType: string;
  data: string;
}

export function extractAttachments(data: Record<string, unknown>): MessageAttachment[] {
  const attachments: MessageAttachment[] = [];
  let counter = 0;

  function pushAttachment(dataValue: string, siblings?: Record<string, unknown>, fallbackName?: string) {
    const doc = detectDocument(dataValue, siblings);
    if (!doc) {
      return;
    }

    counter += 1;
    const ext = getFileExtension(doc.type);
    attachments.push({
      id: `att-${counter}`,
      name: doc.name || fallbackName || `file-${counter}.${ext}`,
      mimeType: doc.mimeType,
      data: doc.data,
    });
  }

  function scan(value: unknown, key?: string, parent?: Record<string, unknown>): void {
    if (typeof value === "string") {
      pushAttachment(value, parent, key);
      return;
    }

    if (Array.isArray(value)) {
      value.forEach((item, index) => scan(item, `${key ?? "item"}-${index}`));
      return;
    }

    if (!value || typeof value !== "object") {
      return;
    }

    const record = value as Record<string, unknown>;

    if (
      record.type === "image_url" &&
      record.image_url &&
      typeof (record.image_url as Record<string, unknown>).url === "string"
    ) {
      pushAttachment((record.image_url as Record<string, unknown>).url as string, record, "image");
      return;
    }

    if (typeof record.data === "string") {
      const beforeCount = attachments.length;
      pushAttachment(record.data, record, key);
      if (attachments.length > beforeCount) {
        return;
      }
    }

    for (const [childKey, childValue] of Object.entries(record)) {
      scan(childValue, childKey, record);
    }
  }

  scan(data);
  return attachments;
}
