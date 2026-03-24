// Layout mode: 'grid' (multi-column) or 'stack' (single-column chronological)
export type LayoutMode = 'grid' | 'stack';
export const LAYOUT_MODE: LayoutMode = 'stack';

// Node dimensions
export const NODE_WIDTH = 150;
export const NODE_HEIGHT = 32;

// Node styling
export const NODE_BORDER_WIDTH = 1;

// Layout spacing
export const LAYER_SPACING = 0;  // Grid layout
export const STACK_LAYER_SPACING = 24;  // Stack layout vertical gap between nodes
export const NODE_SPACING = 20;
export const BAND_SPACING = 15;

// UI: Top margin above the ReactFlow canvas (in px)
export const FLOW_CONTAINER_MARGIN_TOP = 30;

// Visual spacing between multiple band arrows entering the same target
// Pixels between adjacent arrow entries (increase to give more space between arrows)
export const BAND_ENTRY_STAGGER_STEP = 4;
// Maximum absolute vertical offset applied at the target when staggering entries
// Must be less than NODE_HEIGHT/2 to keep arrows within node bounds
export const BAND_ENTRY_STAGGER_CLAMP = 8;

// Color palettes for band edges - cycles through these colors
// Light colors for dark backgrounds
export const BAND_COLORS_DARK_BG = [
  '#64B5F6', // light blue
  '#81C784', // light green
  '#FFB74D', // light orange
  '#FFF176', // light yellow
  '#4FC3F7', // sky blue
  '#AED581', // lime green
  '#FFD54F', // amber
  '#4DD0E1', // cyan
  '#A5D6A7', // pale green
  '#FFCC80', // peach
  '#90CAF9', // pale blue
  '#C5E1A5', // light lime
];

// Dark colors for light backgrounds
export const BAND_COLORS_LIGHT_BG = [
  '#1565C0', // dark blue
  '#2E7D32', // dark green
  '#E65100', // dark orange
  '#F9A825', // dark yellow
  '#0277BD', // dark sky blue
  '#558B2F', // dark lime
  '#FF8F00', // dark amber
  '#00838F', // dark cyan
  '#388E3C', // forest green
  '#EF6C00', // burnt orange
  '#1976D2', // medium blue
  '#689F38', // olive green
];

// Helper to get band color by index (wraps around)
export function getBandColor(index: number, isDarkBackground: boolean): string {
  const palette = isDarkBackground ? BAND_COLORS_DARK_BG : BAND_COLORS_LIGHT_BG;
  return palette[index % palette.length];
}

// Fallback stroke color for bands without an explicit color mapping
export const DEFAULT_BAND_COLOR = '#e0e0e0';