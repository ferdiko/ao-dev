import { LayoutNode, LayerInfo, BandInfo } from '../core/types';
import { BAND_SPACING, DEFAULT_BAND_COLOR } from '../../layoutConstants';

export interface StackLayoutConfig {
  nodeWidth: number;
  nodeHeight: number;
  layerSpacing: number;
  bandSpacing: number;
  containerWidth: number;
}

/**
 * Stack layout: single-column, chronological ordering.
 * Each node gets its own layer, centered horizontally.
 */
export function calculateStackLayout(
  nodes: LayoutNode[],
  cfg: StackLayoutConfig
): { layers: LayerInfo[]; bands: BandInfo[] } {
  const { nodeWidth, nodeHeight, layerSpacing, bandSpacing, containerWidth } = cfg;

  // 1. Assign layers chronologically (index = layer)
  // Center each node horizontally
  const centerX = (containerWidth - nodeWidth) / 2;

  nodes.forEach((node, i) => {
    node.layer = i;
    node.visualLayer = i;
    node.x = centerX;
    node.y = i * (nodeHeight + layerSpacing);
    node.width = nodeWidth;
    node.height = nodeHeight;
  });

  // 2. Build LayerInfo (one node per layer)
  const layers: LayerInfo[] = nodes.map((node, i) => ({
    layer: i,
    visualLayers: [[node.id]],
    nodes: [node]
  }));

  // 3. Calculate bands for skip-layer edges
  const bands = calculateStackBands(nodes, cfg);

  return { layers, bands };
}

/**
 * Simplified band calculation for stack layout.
 * Only nodes with skip-layer children (non-consecutive layers) need bands.
 */
function calculateStackBands(
  nodes: LayoutNode[],
  cfg: StackLayoutConfig
): BandInfo[] {
  const { nodeWidth, bandSpacing, containerWidth } = cfg;
  const bands: BandInfo[] = [];

  // Find nodes that need bands (have skip-layer children)
  const needsBand = (node: LayoutNode): boolean => {
    return node.children.some(cid => {
      const child = nodes.find(n => n.id === cid);
      return child && child.layer !== node.layer! + 1;
    });
  };

  const nodesNeedingBands = nodes.filter(needsBand);
  if (nodesNeedingBands.length === 0) {
    return bands;
  }

  // Calculate node area boundaries
  const nodeAreaStart = Math.min(...nodes.map(n => n.x!));
  const nodeAreaEnd = Math.max(...nodes.map(n => n.x! + n.width!));

  // Track band segments to avoid overlap
  type BandSegment = { startY: number; endY: number };
  const existingBands: Record<string, BandSegment[]> = {};
  const usedLevels = new Set<number>();

  // Simple segment intersection check
  const segmentsOverlap = (a: BandSegment, b: BandSegment): boolean => {
    return !(a.endY <= b.startY || a.startY >= b.endY);
  };

  const findAvailableBand = (node: LayoutNode): string => {
    const nodeChildren = node.children
      .map(cid => nodes.find(n => n.id === cid))
      .filter(Boolean) as LayoutNode[];

    if (nodeChildren.length === 0) return "Band 1 Right";

    // Calculate vertical segment this node would occupy
    const maxChildY = Math.max(...nodeChildren.map(c => c.y!));
    const exitY = node.y! + node.height! * 0.65;
    const newSegment: BandSegment = {
      startY: Math.min(exitY, maxChildY),
      endY: Math.max(exitY, maxChildY)
    };

    // Try to find an available band level
    for (let level = 1; level <= 10; level++) {
      // Alternate sides to spread bands out
      const sides = level % 2 === 1 ? ['right', 'left'] as const : ['left', 'right'] as const;

      for (const side of sides) {
        const bandName = `Band ${level} ${side === 'right' ? 'Right' : 'Left'}`;
        const existing = existingBands[bandName] || [];

        const hasOverlap = existing.some(seg => segmentsOverlap(newSegment, seg));
        if (!hasOverlap) {
          if (!existingBands[bandName]) existingBands[bandName] = [];
          existingBands[bandName].push(newSegment);
          usedLevels.add(level);
          return bandName;
        }
      }
    }

    // Fallback: create new level
    const fallbackLevel = Math.max(...Array.from(usedLevels), 0) + 1;
    const fallbackName = `Band ${fallbackLevel} Right`;
    usedLevels.add(fallbackLevel);
    if (!existingBands[fallbackName]) existingBands[fallbackName] = [];
    existingBands[fallbackName].push(newSegment);
    return fallbackName;
  };

  // Assign bands to nodes (process in layer order)
  nodesNeedingBands.sort((a, b) => a.layer! - b.layer!);
  nodesNeedingBands.forEach(node => {
    node.band = findAvailableBand(node);
  });

  // Create BandInfo entries for all used levels
  // Colors are assigned at render time in GraphView, so use placeholder here
  const maxLevel = Math.max(...Array.from(usedLevels), 0);
  for (let level = 1; level <= maxLevel; level++) {
    bands.push({
      name: `Band ${level} Right`,
      x: nodeAreaEnd + 15 + (level - 1) * bandSpacing,
      side: 'right',
      level,
      color: DEFAULT_BAND_COLOR
    });
    bands.push({
      name: `Band ${level} Left`,
      x: nodeAreaStart - 15 - (level - 1) * bandSpacing,
      side: 'left',
      level,
      color: DEFAULT_BAND_COLOR
    });
  }

  return bands;
}
