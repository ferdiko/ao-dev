export type MessageRoleTone = "user" | "assistant" | "system" | "developer" | "tool" | "critic" | "unknown";

export interface MessageRoleStyle {
  label: string;
  tone: MessageRoleTone;
  light: {
    background: string;
    border: string;
    text: string;
  };
  dark: {
    background: string;
    border: string;
    text: string;
  };
}

export interface MessageMetadataEntry {
  key: string;
  path: string[];
  value: unknown;
}

export interface MessageLikeObject {
  role: string;
  roleStyle: MessageRoleStyle;
  content: unknown;
  contentPath: string[];
  metadata: MessageMetadataEntry[];
}

export interface FlattenedMessageGroup {
  messageKey: string;
  path: string[];
  messageValue: unknown;
  detectedMessage: MessageLikeObject | null;
  detectedMessages: MessageLikeObject[] | null;
  metadata: MessageMetadataEntry[];
  consumedKeys: string[];
}

const FLATTENED_ROLE_RE = /^(?<prefix>[A-Za-z0-9_.-]+)\.role$/;
const FLATTENED_CONTENT_SUFFIXES = ["content", "parts", "text", "tool_calls", "function_call"] as const;
const FLATTENED_MESSAGE_SUFFIXES = ["messages", "message"] as const;

const ROLE_ALIASES: Record<string, MessageRoleTone> = {
  user: "user",
  human: "user",
  assistant: "assistant",
  model: "assistant",
  ai: "assistant",
  system: "system",
  developer: "developer",
  tool: "tool",
  function: "tool",
  critic: "critic",
  discriminator: "critic",
  unknown: "unknown",
};

const ROLE_STYLES: Record<MessageRoleTone, Omit<MessageRoleStyle, "label">> = {
  user: {
    tone: "user",
    light: {
      background: "rgba(32, 119, 219, 0.10)",
      border: "rgba(32, 119, 219, 0.22)",
      text: "#1659a8",
    },
    dark: {
      background: "rgba(96, 165, 250, 0.14)",
      border: "rgba(96, 165, 250, 0.28)",
      text: "#b7d6ff",
    },
  },
  assistant: {
    tone: "assistant",
    light: {
      background: "rgba(24, 135, 84, 0.10)",
      border: "rgba(24, 135, 84, 0.22)",
      text: "#166746",
    },
    dark: {
      background: "rgba(52, 211, 153, 0.14)",
      border: "rgba(52, 211, 153, 0.26)",
      text: "#b7f3d7",
    },
  },
  system: {
    tone: "system",
    light: {
      background: "rgba(180, 83, 9, 0.10)",
      border: "rgba(180, 83, 9, 0.22)",
      text: "#9a5a06",
    },
    dark: {
      background: "rgba(251, 191, 36, 0.14)",
      border: "rgba(251, 191, 36, 0.26)",
      text: "#fde7a0",
    },
  },
  developer: {
    tone: "developer",
    light: {
      background: "rgba(124, 58, 237, 0.10)",
      border: "rgba(124, 58, 237, 0.20)",
      text: "#6d31cf",
    },
    dark: {
      background: "rgba(167, 139, 250, 0.14)",
      border: "rgba(167, 139, 250, 0.28)",
      text: "#ddd2ff",
    },
  },
  tool: {
    tone: "tool",
    light: {
      background: "rgba(13, 148, 136, 0.10)",
      border: "rgba(13, 148, 136, 0.20)",
      text: "#0f6f67",
    },
    dark: {
      background: "rgba(45, 212, 191, 0.14)",
      border: "rgba(45, 212, 191, 0.26)",
      text: "#b5f3eb",
    },
  },
  critic: {
    tone: "critic",
    light: {
      background: "rgba(190, 24, 93, 0.10)",
      border: "rgba(190, 24, 93, 0.20)",
      text: "#a61b57",
    },
    dark: {
      background: "rgba(244, 114, 182, 0.14)",
      border: "rgba(244, 114, 182, 0.24)",
      text: "#ffd3e8",
    },
  },
  unknown: {
    tone: "unknown",
    light: {
      background: "rgba(107, 114, 128, 0.08)",
      border: "rgba(107, 114, 128, 0.18)",
      text: "#5b6472",
    },
    dark: {
      background: "rgba(148, 163, 184, 0.10)",
      border: "rgba(148, 163, 184, 0.22)",
      text: "#d6dde8",
    },
  },
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function inferRoleTone(role: string): MessageRoleTone {
  return ROLE_ALIASES[role.trim().toLowerCase()] ?? "unknown";
}

function normalizeRoleLabel(role: string): string {
  const trimmed = role.trim();
  return trimmed ? trimmed.toLowerCase() : "unknown";
}

function simplifyMessageContent(value: unknown): unknown {
  if (!Array.isArray(value) || value.length === 0) {
    return value;
  }

  const textParts = value.map((item) => {
    if (!isRecord(item)) {
      return null;
    }

    if (typeof item.text === "string") {
      return item.text;
    }

    return null;
  });

  if (textParts.every((part) => typeof part === "string")) {
    return textParts.join("\n\n");
  }

  return value;
}

function isScalarMetadataValue(value: unknown): boolean {
  return value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function buildDirectMessage(record: Record<string, unknown>, prefix: string[] = []): MessageLikeObject | null {
  if (typeof record.role !== "string") {
    return null;
  }

  const candidateContentKeys = ["content", "parts", "text", "tool_calls", "function_call"] as const;
  const contentKey = candidateContentKeys.find((key) => key in record);
  if (!contentKey) {
    return null;
  }

  const metadata = Object.entries(record)
    .filter(([key, value]) => {
      if (key === "role" || key === contentKey) {
        return false;
      }

      if (key === "type" && value === "message") {
        return false;
      }

      return true;
    })
    .map(([key, value]) => ({ key, path: [...prefix, key], value }));

  return {
    role: record.role,
    roleStyle: getMessageRoleStyle(record.role),
    content: simplifyMessageContent(record[contentKey]),
    contentPath: [...prefix, contentKey],
    metadata,
  };
}

function buildFlattenedMessage(record: Record<string, unknown>): MessageLikeObject | null {
  for (const [key, value] of Object.entries(record)) {
    const match = key.match(FLATTENED_ROLE_RE);
    if (!match?.groups?.prefix || typeof value !== "string") {
      continue;
    }

    const prefix = match.groups.prefix;
    const contentKey = FLATTENED_CONTENT_SUFFIXES
      .map((suffix) => `${prefix}.${suffix}`)
      .find((candidateKey) => candidateKey in record);

    if (!contentKey) {
      continue;
    }

    const metadata = Object.entries(record)
      .filter(([entryKey, entryValue]) => {
        if (entryKey === key || entryKey === contentKey) {
          return false;
        }

        if (entryKey === `${prefix}.type` && entryValue === "message") {
          return false;
        }

        return true;
      })
      .map(([entryKey, entryValue]) => ({
        key: entryKey,
        path: [entryKey],
        value: entryValue,
      }));

    return {
      role: value,
      roleStyle: getMessageRoleStyle(value),
      content: simplifyMessageContent(record[contentKey]),
      contentPath: [contentKey],
      metadata,
    };
  }

  return null;
}

export function getMessageRoleStyle(role: string): MessageRoleStyle {
  const label = normalizeRoleLabel(role);
  const tone = inferRoleTone(role);
  return {
    label,
    ...ROLE_STYLES[tone],
  };
}

export function detectMessageLikeObject(value: unknown): MessageLikeObject | null {
  if (!isRecord(value)) {
    return null;
  }

  const direct = buildDirectMessage(value);
  if (direct) {
    return direct;
  }

  const flattened = buildFlattenedMessage(value);
  if (flattened) {
    return flattened;
  }

  if (isRecord(value.message)) {
    const nested = buildDirectMessage(value.message, ["message"]);
    if (nested) {
      const outerMetadata = Object.entries(value)
        .filter(([key]) => key !== "message")
        .map(([key, itemValue]) => ({ key, path: [key], value: itemValue }));

      return {
        ...nested,
        metadata: [...outerMetadata, ...nested.metadata],
      };
    }
  }

  return null;
}

export function detectMessageLikeArray(value: unknown[]): MessageLikeObject[] | null {
  if (value.length === 0) {
    return null;
  }

  const detected = value.map((item) => detectMessageLikeObject(item));
  if (detected.every((item) => item !== null)) {
    return detected;
  }

  return null;
}

export function detectFlattenedMessageGroups(record: Record<string, unknown>): FlattenedMessageGroup[] {
  const groupedEntries = new Map<string, Array<{ fullKey: string; suffix: string; value: unknown }>>();

  for (const [key, value] of Object.entries(record)) {
    const splitIndex = key.lastIndexOf(".");
    if (splitIndex <= 0) {
      continue;
    }

    const prefix = key.slice(0, splitIndex);
    const suffix = key.slice(splitIndex + 1);
    const bucket = groupedEntries.get(prefix) ?? [];
    bucket.push({ fullKey: key, suffix, value });
    groupedEntries.set(prefix, bucket);
  }

  const groups: FlattenedMessageGroup[] = [];

  for (const entries of groupedEntries.values()) {
    const messageEntry = entries.find(({ suffix, value }) => {
      if (!FLATTENED_MESSAGE_SUFFIXES.includes(suffix as (typeof FLATTENED_MESSAGE_SUFFIXES)[number])) {
        return false;
      }

      if (Array.isArray(value)) {
        return detectMessageLikeArray(value) !== null;
      }

      return detectMessageLikeObject(value) !== null;
    });

    if (!messageEntry) {
      continue;
    }

    const detectedMessages = Array.isArray(messageEntry.value) ? detectMessageLikeArray(messageEntry.value) : null;
    const detectedMessage = !Array.isArray(messageEntry.value) ? detectMessageLikeObject(messageEntry.value) : null;

    if (!detectedMessages && !detectedMessage) {
      continue;
    }

    const metadata = entries
      .filter(({ fullKey, value }) => fullKey !== messageEntry.fullKey && isScalarMetadataValue(value))
      .map(({ suffix, fullKey, value }) => ({
        key: suffix,
        path: [fullKey],
        value,
      }));

    if (metadata.length === 0) {
      continue;
    }

    groups.push({
      messageKey: messageEntry.fullKey,
      path: [messageEntry.fullKey],
      messageValue: messageEntry.value,
      detectedMessage,
      detectedMessages,
      metadata,
      consumedKeys: [messageEntry.fullKey, ...metadata.map((entry) => entry.path[0])],
    });
  }

  return groups;
}
