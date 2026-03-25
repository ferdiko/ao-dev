export interface Tag {
  tag_id: string;
  name: string;
  color: string;
}

export const TAG_COLORS = [
  "#6F7C8B",
  "#7E8F6A",
  "#6E8B7B",
  "#7F6A8A",
  "#8A6F66",
  "#6A8C93",
  "#9A865F",
  "#7A7F97",
  "#8C7474",
  "#637A72",
] as const;

export function contrastTagText(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.55 ? "#1a1a1a" : "#ffffff";
}

export function sortTagsByName(tags: Tag[]): Tag[] {
  return [...tags].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
}
