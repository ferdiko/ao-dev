// Returns only the date part (YYYY-MM-DD) from a timestamp like '2024-06-21 12:00:00'
export function getDateOnly(timestamp?: string): string {
    if (!timestamp) return '';
    return timestamp.split(' ')[0];
}