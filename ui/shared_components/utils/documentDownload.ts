import { getFileExtension } from "./documentDetection";
import type { DetectedDocument } from "./documentDetection";

interface SaveFileWriter {
  write(data: Blob): Promise<void>;
  close(): Promise<void>;
}

interface SaveFileHandle {
  createWritable(): Promise<SaveFileWriter>;
}

interface SavePickerWindow extends Window {
  showSaveFilePicker?: (options?: {
    suggestedName?: string;
    types?: Array<{
      description?: string;
      accept: Record<string, string[]>;
    }>;
  }) => Promise<SaveFileHandle>;
}

export function createDocumentBlob(doc: Pick<DetectedDocument, "data" | "mimeType">): Blob {
  const binary = atob(doc.data);
  const bytes = new Uint8Array(binary.length);

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  return new Blob([bytes], { type: doc.mimeType });
}

export function getDocumentFileName(doc: Pick<DetectedDocument, "type" | "name">): string {
  return doc.name || `document.${getFileExtension(doc.type)}`;
}

export function triggerDocumentDownload(doc: Pick<DetectedDocument, "data" | "mimeType" | "type" | "name">): void {
  const blob = createDocumentBlob(doc);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = getDocumentFileName(doc);
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

export async function saveDocumentWithPicker(
  doc: Pick<DetectedDocument, "data" | "mimeType" | "type" | "name">,
): Promise<boolean> {
  const pickerWindow = window as SavePickerWindow;
  if (!pickerWindow.showSaveFilePicker || !window.isSecureContext) {
    return false;
  }

  try {
    const handle = await pickerWindow.showSaveFilePicker({
      suggestedName: getDocumentFileName(doc),
      types: [
        {
          description: doc.mimeType,
          accept: { [doc.mimeType]: [`.${getFileExtension(doc.type)}`] },
        },
      ],
    });
    const writable = await handle.createWritable();
    await writable.write(createDocumentBlob(doc));
    await writable.close();
    return true;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return true;
    }
    return false;
  }
}

export async function saveDocument(
  doc: Pick<DetectedDocument, "data" | "mimeType" | "type" | "name">,
): Promise<void> {
  const savedWithPicker = await saveDocumentWithPicker(doc);
  if (!savedWithPicker) {
    triggerDocumentDownload(doc);
  }
}
