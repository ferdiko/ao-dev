const SOVARA_PRIORS_BLOCK_RE = /<sovara-priors\b[^>]*>[\s\S]*?<\/sovara-priors>/gi;

export function stripSovaraPriorsBlocks(text: string): string {
  if (!text) {
    return text;
  }

  return text
    .replace(SOVARA_PRIORS_BLOCK_RE, "")
    .replace(/\n{3,}/g, "\n\n");
}

export function stripSovaraPriorsFromValue<T>(value: T): T {
  if (typeof value === "string") {
    return stripSovaraPriorsBlocks(value) as T;
  }

  if (Array.isArray(value)) {
    return value.map((item) => stripSovaraPriorsFromValue(item)) as T;
  }

  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        stripSovaraPriorsFromValue(item),
      ]),
    ) as T;
  }

  return value;
}
