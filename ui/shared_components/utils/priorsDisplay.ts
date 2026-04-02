const SOVARA_PRIORS_BLOCK_RE = /<sovara-priors\b[^>]*>[\s\S]*?<\/sovara-priors>/gi;
const SOVARA_PRIORS_BLOCK_WITH_SEPARATOR_RE =
  /<sovara-priors\b[^>]*>[\s\S]*?<\/sovara-priors>\n\n/gi;

export function stripSovaraPriorsBlocks(text: string): string {
  if (!text) {
    return text;
  }

  const withoutManagedSeparator = text.replace(
    SOVARA_PRIORS_BLOCK_WITH_SEPARATOR_RE,
    "",
  );
  return withoutManagedSeparator.replace(SOVARA_PRIORS_BLOCK_RE, "");
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
