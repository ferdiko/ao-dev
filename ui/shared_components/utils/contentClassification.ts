import { parse as parseLossless } from 'lossless-json';
import { detectDocument } from './documentDetection';

export interface LosslessNumberLike {
  isLosslessNumber: true;
  value: string;
}

export type StringClassification =
  | { kind: 'json'; parsed: unknown; label: 'json object' | 'json list' }
  | { kind: 'markdown' }
  | { kind: 'code'; language: string; fenced: boolean }
  | { kind: 'xml' }
  | { kind: 'plain' };

const FENCED_CODE_RE = /^```([a-zA-Z0-9_+-]+)?\n([\s\S]*?)\n```$/;
const XML_RE = /^<([A-Za-z_][\w:.-]*)(\s+[^<>]*)?>[\s\S]*<\/\1>$|^<([A-Za-z_][\w:.-]*)(\s+[^<>]*)?\/>$/;
const STRONG_MARKDOWN_PATTERNS = [
  /^#{1,6}\s/m,
  /^[-*+]\s/m,
  /^\d+\.\s/m,
  /^>\s/m,
  /\|.+\|/,
  /\[[^\]]+\]\([^)]+\)/,
  /```[\s\S]*```/,
];

export function isLosslessNumberValue(value: unknown): value is LosslessNumberLike {
  return value !== null && typeof value === 'object' && (value as LosslessNumberLike).isLosslessNumber === true;
}

export function unwrapLosslessNumber(value: unknown): unknown {
  if (!isLosslessNumberValue(value)) {
    return value;
  }

  return Number(value.value);
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) && !isLosslessNumberValue(value);
}

export function isScalarValue(value: unknown): boolean {
  return (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    isLosslessNumberValue(value)
  );
}

export function getScalarTypeLabel(value: unknown): 'null' | 'string' | 'int' | 'float' | 'boolean' {
  if (value === null) {
    return 'null';
  }

  if (typeof value === 'string') {
    return 'string';
  }

  if (typeof value === 'boolean') {
    return 'boolean';
  }

  const numericValue = unwrapLosslessNumber(value);
  if (typeof numericValue === 'number') {
    return Number.isInteger(numericValue) ? 'int' : 'float';
  }

  return 'string';
}

export function classifyStringContent(value: string): StringClassification {
  const trimmed = value.trim();
  if (!trimmed) {
    return { kind: 'plain' };
  }

  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const parsed = parseLossless(trimmed);
      if (Array.isArray(parsed)) {
        return { kind: 'json', parsed, label: 'json list' };
      }
      if (isRecord(parsed)) {
        return { kind: 'json', parsed, label: 'json object' };
      }
    } catch {
      // Fall through to other classifiers.
    }
  }

  const fenced = trimmed.match(FENCED_CODE_RE);
  if (fenced) {
    const language = normalizeLanguage(fenced[1]) || inferCodeLanguage(fenced[2]);
    return { kind: 'code', language, fenced: true };
  }

  if (looksLikeXml(trimmed)) {
    return { kind: 'xml' };
  }

  if (looksLikeMarkdown(value)) {
    return { kind: 'markdown' };
  }

  const inferredLanguage = inferUnfencedCodeLanguage(value);
  if (inferredLanguage) {
    return { kind: 'code', language: inferredLanguage, fenced: false };
  }

  return { kind: 'plain' };
}

export function isPrimitiveArray(value: unknown[]): boolean {
  return value.every((item) => isScalarValue(item));
}

export function getUniformObjectArrayColumns(value: unknown[]): string[] | null {
  if (value.length === 0 || !value.every((item) => isRecord(item))) {
    return null;
  }

  const firstColumns = Object.keys(value[0] as Record<string, unknown>);
  if (firstColumns.length === 0 || firstColumns.length > 8) {
    return null;
  }

  const signature = firstColumns.join('\u0000');
  for (const item of value as Record<string, unknown>[]) {
    if (Object.keys(item).join('\u0000') !== signature) {
      return null;
    }
    for (const key of firstColumns) {
      const cell = item[key];
      if (!isScalarValue(cell)) {
        return null;
      }

      if (typeof cell === 'string') {
        if (detectDocument(cell, item) || shouldCollapseLongText(cell)) {
          return null;
        }

        if (classifyStringContent(cell).kind !== 'plain') {
          return null;
        }
      }
    }
  }

  return firstColumns;
}

export function shouldCollapseLongText(value: string): boolean {
  return value.length > 360 || value.split('\n').length > 10;
}

export function getStringPreview(value: string, maxLength = 180): string {
  if (value.length <= maxLength) {
    return value;
  }

  return `${value.slice(0, maxLength).trimEnd()}…`;
}

export function unwrapFencedCode(value: string): { language: string; code: string } | null {
  const trimmed = value.trim();
  const match = trimmed.match(FENCED_CODE_RE);
  if (!match) {
    return null;
  }

  return {
    language: normalizeLanguage(match[1]) || inferCodeLanguage(match[2]),
    code: match[2],
  };
}

function looksLikeXml(value: string): boolean {
  return XML_RE.test(value);
}

function looksLikeMarkdown(value: string): boolean {
  if (STRONG_MARKDOWN_PATTERNS.some((pattern) => pattern.test(value))) {
    return true;
  }

  const inlineCodeMatches = value.match(/`[^`\n]+`/g) || [];
  if (inlineCodeMatches.length >= 2 && value.includes('\n')) {
    return true;
  }

  return false;
}

function inferUnfencedCodeLanguage(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed.includes('\n') && trimmed.length < 24) {
    return null;
  }

  const language = inferCodeLanguage(trimmed);
  if (language === 'text') {
    return null;
  }

  const looksCodeLike =
    /[{}();=]/.test(trimmed) ||
    /\b(function|class|def|import|export|return|SELECT|FROM|WHERE|package|func)\b/.test(trimmed);

  return looksCodeLike ? language : null;
}

function inferCodeLanguage(value: string): string {
  const trimmed = value.trim();

  if (/^\s*SELECT\b[\s\S]*\bFROM\b/i.test(trimmed) || /\bGROUP BY\b/i.test(trimmed)) {
    return 'sql';
  }

  if (/^\s*(def |from |import )/m.test(trimmed) || /\blambda\b/.test(trimmed)) {
    return 'python';
  }

  if (/^\s*package\s+\w+/m.test(trimmed) && /\bfunc\s+\w+\(/.test(trimmed)) {
    return 'go';
  }

  if (/^\s*#\!\/bin\/(ba)?sh/m.test(trimmed) || /(^|\n)\s*(echo|export|cd|grep|uv|python3?)\b/.test(trimmed)) {
    return 'bash';
  }

  if (/<[A-Za-z]/.test(trimmed) && /\{ label\s*:/.test(trimmed)) {
    return 'tsx';
  }

  if (/\binterface\s+\w+/.test(trimmed) || /\btype\s+\w+\s*=/.test(trimmed) || /\bexport\s+function\b/.test(trimmed)) {
    return 'typescript';
  }

  if (/\bfunction\b/.test(trimmed) || /\bconsole\./.test(trimmed) || /=>/.test(trimmed)) {
    return 'javascript';
  }

  if (looksLikeXml(trimmed)) {
    return 'xml';
  }

  return 'text';
}

function normalizeLanguage(language: string | undefined): string | null {
  if (!language) {
    return null;
  }

  const normalized = language.trim().toLowerCase();
  if (!normalized) {
    return null;
  }

  if (normalized === 'js') {
    return 'javascript';
  }

  if (normalized === 'ts') {
    return 'typescript';
  }

  return normalized;
}
