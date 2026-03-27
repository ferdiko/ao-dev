// Returns only the date part (YYYY-MM-DD) from a timestamp like '2024-06-21 12:00:00'
export function getDateOnly(timestamp?: string): string {
    if (!timestamp) return '';
    return timestamp.split(' ')[0];
}

export function parseUtcTimestamp(raw: string): number {
    const normalized = raw.replace(' ', 'T');
    return new Date(normalized.endsWith('Z') ? normalized : `${normalized}Z`).getTime();
}

export function formatUtcTimestamp(
    raw?: string,
    options?: Intl.DateTimeFormatOptions,
): string {
    if (!raw) return '—';
    const milliseconds = parseUtcTimestamp(raw);
    if (Number.isNaN(milliseconds)) return raw;

    return new Date(milliseconds).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
        hourCycle: 'h23',
        ...options,
    });
}
