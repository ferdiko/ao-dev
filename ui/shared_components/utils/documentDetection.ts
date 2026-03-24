/**
 * Document detection for base64-encoded files in JSON values.
 * Detects PDFs, images, and Office documents by MIME type hints or magic numbers.
 */

export interface DetectedDocument {
  type: "pdf" | "png" | "jpeg" | "gif" | "webp" | "docx" | "xlsx" | "zip" | "unknown";
  mimeType: string;
  size: number;      // base64 string length
  data: string;      // the base64 string itself
}

// Magic number prefixes (base64-encoded)
const BASE64_MAGIC: Record<string, { type: DetectedDocument["type"]; mime: string }> = {
  "JVBERi": { type: "pdf", mime: "application/pdf" },
  "iVBORw0KGgo": { type: "png", mime: "image/png" },
  "/9j/": { type: "jpeg", mime: "image/jpeg" },
  "R0lGOD": { type: "gif", mime: "image/gif" },
  "UklGR": { type: "webp", mime: "image/webp" },
  "UEsDB": { type: "zip", mime: "application/zip" },  // Also DOCX/XLSX
  "0M8R4KGx": { type: "unknown", mime: "application/octet-stream" },  // Old Office
};

// MIME type to document type mapping
const MIME_TYPE_MAP: Record<string, DetectedDocument["type"]> = {
  "application/pdf": "pdf",
  "image/png": "png",
  "image/jpeg": "jpeg",
  "image/gif": "gif",
  "image/webp": "webp",
  "application/zip": "zip",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "unknown",
};

/**
 * Extract MIME type from sibling keys in the JSON structure.
 * Handles common patterns like Anthropic's { media_type: "...", data: "..." }
 */
function extractMimeFromSiblings(siblings?: Record<string, unknown>): string | null {
  if (!siblings) return null;

  // Anthropic: { "media_type": "application/pdf", "data": "..." }
  if (typeof siblings.media_type === "string") return siblings.media_type;

  // Generic patterns
  if (typeof siblings.content_type === "string") return siblings.content_type;
  if (typeof siblings.contentType === "string") return siblings.contentType;
  if (typeof siblings.mime_type === "string") return siblings.mime_type;
  if (typeof siblings.mimeType === "string") return siblings.mimeType;

  return null;
}

/**
 * Create a DetectedDocument from a known MIME type.
 */
function fromMimeType(mime: string, data: string): DetectedDocument {
  return {
    type: MIME_TYPE_MAP[mime] || "unknown",
    mimeType: mime,
    size: data.length,
    data,
  };
}

/**
 * Detect if a string value is a base64-encoded document.
 *
 * Detection priority:
 * 1. MIME type from sibling keys (media_type, content_type, etc.)
 * 2. Data URL prefix (data:image/png;base64,...)
 * 3. Magic number detection from base64 prefix
 *
 * @param value - The string value to check
 * @param siblingData - Parent object containing sibling keys (for MIME hints)
 * @returns DetectedDocument if detected, null otherwise
 */
export function detectDocument(
  value: unknown,
  siblingData?: Record<string, unknown>
): DetectedDocument | null {
  if (typeof value !== "string" || value.length < 50) return null;

  // 1. Check MIME type from sibling keys
  const mimeHint = extractMimeFromSiblings(siblingData);
  if (mimeHint && MIME_TYPE_MAP[mimeHint]) {
    return fromMimeType(mimeHint, value);
  }

  // 2. Check data URL prefix: "data:image/png;base64,..."
  const dataUrlMatch = value.match(/^data:([^;]+);base64,(.+)$/);
  if (dataUrlMatch) {
    const [, mime, data] = dataUrlMatch;
    return fromMimeType(mime, data);
  }

  // 3. Fall back to magic number detection
  for (const [magic, info] of Object.entries(BASE64_MAGIC)) {
    if (value.startsWith(magic)) {
      return { type: info.type, mimeType: info.mime, size: value.length, data: value };
    }
  }

  return null;
}

/**
 * Format base64 string length as human-readable file size.
 * Accounts for base64 overhead (~33%).
 */
export function formatFileSize(base64Length: number): string {
  const bytes = Math.round(base64Length * 0.75);  // base64 overhead
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Get file extension for a document type.
 */
export function getFileExtension(type: DetectedDocument["type"]): string {
  const extensions: Record<DetectedDocument["type"], string> = {
    pdf: "pdf",
    png: "png",
    jpeg: "jpg",
    gif: "gif",
    webp: "webp",
    docx: "docx",
    xlsx: "xlsx",
    zip: "zip",
    unknown: "bin",
  };
  return extensions[type];
}

/**
 * Generate a short key from base64 data for tracking opened documents.
 * Uses first 32 chars which should be unique enough to identify documents.
 */
export function getDocumentKey(base64Data: string): string {
  return base64Data.substring(0, 32);
}
