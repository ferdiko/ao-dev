import {
  detectDocument,
  type DetectedDocument,
  getFileExtensionsForDocumentType,
  getMimeTypeForDocumentType,
} from "./documentDetection";

export interface ReplacementDocumentFile {
  name: string;
  mimeType: string;
  data: string;
  type: DetectedDocument["type"];
}

export const DOCUMENT_FILENAME_KEYS = ["filename", "file_name", "name"] as const;
export const DOCUMENT_MIME_KEYS = ["mime_type", "mimeType", "media_type", "content_type", "contentType"] as const;

type SaveOpenFileHandle = {
  getFile(): Promise<File>;
};

type PickerWindow = Window & {
  showOpenFilePicker?: (options?: {
    multiple?: boolean;
    excludeAcceptAllOption?: boolean;
    types?: Array<{
      description?: string;
      accept: Record<string, string[]>;
    }>;
  }) => Promise<SaveOpenFileHandle[]>;
};

function cloneDocumentRoot<T>(value: T): T {
  if (typeof structuredClone === "function") {
    return structuredClone(value);
  }

  if (value === undefined) {
    return value;
  }

  return JSON.parse(JSON.stringify(value)) as T;
}

function inferTypeFromName(fileName: string): DetectedDocument["type"] {
  const normalized = fileName.trim().toLowerCase();
  if (normalized.endsWith(".pdf")) return "pdf";
  if (normalized.endsWith(".png")) return "png";
  if (normalized.endsWith(".jpg") || normalized.endsWith(".jpeg")) return "jpeg";
  if (normalized.endsWith(".gif")) return "gif";
  if (normalized.endsWith(".webp")) return "webp";
  if (normalized.endsWith(".docx")) return "docx";
  if (normalized.endsWith(".xlsx")) return "xlsx";
  if (normalized.endsWith(".pptx")) return "pptx";
  if (normalized.endsWith(".zip")) return "zip";
  return "unknown";
}

export function inferDocumentTypeFromMimeOrName(mimeType: string, fileName: string): DetectedDocument["type"] {
  const normalizedMime = mimeType.trim().toLowerCase();
  if (normalizedMime === "application/pdf") return "pdf";
  if (normalizedMime === "image/png") return "png";
  if (normalizedMime === "image/jpeg") return "jpeg";
  if (normalizedMime === "image/gif") return "gif";
  if (normalizedMime === "image/webp") return "webp";
  if (normalizedMime === "application/vnd.openxmlformats-officedocument.wordprocessingml.document") return "docx";
  if (normalizedMime === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") return "xlsx";
  if (normalizedMime === "application/vnd.openxmlformats-officedocument.presentationml.presentation") return "pptx";
  if (normalizedMime === "application/zip") return "zip";
  return inferTypeFromName(fileName);
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";

  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }

  return btoa(binary);
}

async function readReplacementFile(file: File): Promise<ReplacementDocumentFile> {
  const data = arrayBufferToBase64(await file.arrayBuffer());
  const type = inferDocumentTypeFromMimeOrName(file.type || "", file.name);
  return {
    name: file.name,
    mimeType: file.type || getMimeTypeForDocumentType(type),
    data,
    type,
  };
}

function getBrowserAccept(docType: DetectedDocument["type"]): string {
  return getFileExtensionsForDocumentType(docType)
    .map((extension) => `.${extension}`)
    .join(",");
}

async function pickReplacementDocumentWithInput(docType: DetectedDocument["type"]): Promise<ReplacementDocumentFile | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = getBrowserAccept(docType);
    input.style.position = "fixed";
    input.style.left = "-9999px";
    input.style.opacity = "0";

    let settled = false;
    const finish = (value: ReplacementDocumentFile | null) => {
      if (settled) {
        return;
      }

      settled = true;
      window.removeEventListener("focus", handleFocus);
      input.remove();
      resolve(value);
    };

    const handleFocus = () => {
      window.setTimeout(() => {
        if (!settled) {
          finish(null);
        }
      }, 300);
    };

    input.addEventListener(
      "change",
      async () => {
        const file = input.files?.[0];
        if (!file) {
          finish(null);
          return;
        }

        try {
          finish(await readReplacementFile(file));
        } catch {
          finish(null);
        }
      },
      { once: true },
    );

    window.addEventListener("focus", handleFocus, { once: true });
    document.body.appendChild(input);
    input.click();
  });
}

export async function pickReplacementDocumentFromBrowser(
  docType: DetectedDocument["type"],
): Promise<ReplacementDocumentFile | null> {
  const pickerWindow = window as PickerWindow;
  if (pickerWindow.showOpenFilePicker && window.isSecureContext) {
    try {
      const handles = await pickerWindow.showOpenFilePicker({
        multiple: false,
        excludeAcceptAllOption: true,
        types: [
          {
            description: docType.toUpperCase(),
            accept: {
              [getMimeTypeForDocumentType(docType)]: getFileExtensionsForDocumentType(docType).map((extension) => `.${extension}`),
            },
          },
        ],
      });
      const file = await handles[0]?.getFile();
      return file ? readReplacementFile(file) : null;
    } catch {
      return null;
    }
  }

  return pickReplacementDocumentWithInput(docType);
}

function updateFirstMatchingKey(target: Record<string, unknown>, keys: readonly string[], nextValue: string): void {
  for (const key of keys) {
    if (typeof target[key] === "string") {
      target[key] = nextValue;
      return;
    }
  }
}

export function applyDocumentReplacement(
  rootData: unknown,
  path: string[],
  replacement: ReplacementDocumentFile,
): unknown {
  const nextData = cloneDocumentRoot(rootData);
  let current: any = nextData;

  for (let index = 0; index < path.length - 1; index += 1) {
    current = current?.[path[index]];
  }

  const leafKey = path[path.length - 1];
  const currentValue = current?.[leafKey];
  const siblingData = current && typeof current === "object" && !Array.isArray(current)
    ? (current as Record<string, unknown>)
    : undefined;
  const existingDoc = detectDocument(currentValue, siblingData);

  if (!existingDoc || existingDoc.type !== replacement.type) {
    throw new Error("Replacement file type does not match the existing document type.");
  }

  current[leafKey] =
    typeof currentValue === "string" && currentValue.startsWith("data:")
      ? `data:${replacement.mimeType};base64,${replacement.data}`
      : replacement.data;

  if (siblingData) {
    updateFirstMatchingKey(siblingData, DOCUMENT_FILENAME_KEYS, replacement.name);
    updateFirstMatchingKey(siblingData, DOCUMENT_MIME_KEYS, replacement.mimeType);
  }

  return nextData;
}
