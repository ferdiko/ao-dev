import { LayoutNode, LayerInfo, BandInfo } from '../core/types';
import { BAND_SPACING, DEFAULT_BAND_COLOR } from '../../layoutConstants';
import { chooseBandSideForNode } from './bands';
import { wouldDirectLineCrossNodes, hasNodesBetweenInVisualLayers } from './collisions';

export interface BandCalcConfig {
  nodeWidth: number;
  nodeHeight: number;
  nodeSpacing: number;
  layerSpacing: number;
  bandSpacing: number;
  containerWidth: number;
}

// Pure function to compute band allocations and band axis positions.
export function calculateBands(
  nodes: LayoutNode[],
  layers: LayerInfo[],
  cfg: BandCalcConfig
): BandInfo[] {
  const { nodeWidth, nodeSpacing, layerSpacing, bandSpacing, containerWidth } = cfg;
  const bands: BandInfo[] = [];

  const maxNodesPerRow = Math.max(1, Math.floor((containerWidth - nodeSpacing) / (nodeWidth + nodeSpacing)));
  const isSingleColumn = maxNodesPerRow === 1;

  const needsBand = (node: LayoutNode): boolean => {
    const hasSkipLayer = node.children.some(cid => {
      const child = nodes.find(n => n.id === cid);
      return child && child.layer !== (node.layer! + 1);
    });
    let directCross = false;
    if (node.children.length) {
      directCross = node.children.some(cid => {
        const child = nodes.find(n => n.id === cid);
        if (!child || child.layer !== (node.layer! + 1)) return false;
        if (isSingleColumn) {
          const between = nodes.filter(n => n.y! > node.y! + node.height! && n.y! + n.height! < child.y!);
          return between.length > 0;
        }
        return wouldDirectLineCrossNodes(node, child, nodes) || hasNodesBetweenInVisualLayers(node, child, nodes, layerSpacing);
      });
    }
    if (isSingleColumn) return hasSkipLayer || directCross || node.children.length > 1;
    return hasSkipLayer || directCross; // wide screen
  };

  const nodesNeedingBands = nodes.filter(needsBand);

  // Determine node area span
  const allNodes = layers.flatMap(l => l.nodes);
  let nodeAreaStart: number;
  let nodeAreaEnd: number;
  if (allNodes.length) {
    const xs = allNodes.map(n => n.x!);
    nodeAreaStart = Math.min(...xs);
    nodeAreaEnd = Math.max(...allNodes.map(n => n.x! + n.width!));
  } else {
    nodeAreaStart = 30; nodeAreaEnd = containerWidth - 30;
  }

// Structure for tracking existing bands with their segments
  type BandSegment = {
    nodeId: string;
    startY: number;
    endY: number;
    exitY: number; // Y where the node exits
  };
  
  const existingBands: Record<string, BandSegment[]> = {}; // "Band 1 Right" -> [segments]
  const usedLevels = new Set<number>();
  
  const bandExitCrossesNodes = (node: LayoutNode, side: 'left' | 'right', bandX: number): boolean => {
    // Checks if the horizontal segment from the node edge towards the band (to exitY) passes through any other node.
    const exitY = node.y! + node.height! * 0.65;
    const nodeRight = node.x! + node.width!;
    const nodeLeft = node.x!;

    const startX = side === 'right' ? nodeRight : nodeLeft;
    const endX = bandX;
    const minSegX = Math.min(startX, endX);
    const maxSegX = Math.max(startX, endX);

    return nodes.some(n => {
      if (n.id === node.id) return false;
      // Checks if the horizontal segment to exitY vertically intersects node n
      const withinY = exitY >= n.y! && exitY <= n.y! + n.height!;
      if (!withinY) return false;
      const nMinX = n.x!;
      const nMaxX = n.x! + n.width!;
      // Is there overlap in X between the segment and the node's rectangle?
      const overlapsX = !(maxSegX <= nMinX || minSegX >= nMaxX);
      return overlapsX;
    });
  };

  const bandSegmentsIntersect = (newSegment: BandSegment, existingSegments: BandSegment[]): boolean => {
    // Very simple algorithm: conflict if there is direct overlap; use minimal EPS to tolerate rounding
    const EPS = 0.5;
    return existingSegments.some(existing => {
      const hasDirectOverlap = !((newSegment.endY <= existing.startY + EPS) || (newSegment.startY >= existing.endY - EPS));
      return hasDirectOverlap;
    });
  };

  const findAvailableBand = (node: LayoutNode): string => {
    const nodeChildren = node.children.map(cid => nodes.find(n => n.id === cid)).filter(Boolean) as LayoutNode[];
    if (nodeChildren.length === 0) return "Band 1 Right";
    
    // Use the TOP-Y of the lowest child as the segment destination (vertical traversal above centers)
    const maxChildTopY = Math.max(...nodeChildren.map(c => c.y!));
    const exitY = node.y! + node.height! * 0.65;
    // Normalize the segment to avoid inverted or zero-length values
    const segStart = Math.min(exitY, maxChildTopY);
    const segEnd = Math.max(exitY, maxChildTopY);
    const newSegment: BandSegment = {
      nodeId: node.id,
      startY: segStart,
      endY: segEnd === segStart ? segStart + 0.001 : segEnd, // avoid zero-length
      exitY: exitY
    };

    // Find the lowest level
    for (let level = 1; level <= 10; level++) {
      // Test ALL sides of ALL levels before escalating (prefer right)
      const sides = ['right', 'left'] as const;
      
      for (const side of sides) {
        const bandX = side === 'right' 
          ? nodeAreaEnd + 15 + (level - 1) * bandSpacing
          : nodeAreaStart - 15 - (level - 1) * bandSpacing;
        const bandName = `Band ${level} ${side === 'right' ? 'Right' : 'Left'}`;

  // Validate that the horizontal exit towards the band does not cross nodes
  const exitSafe = !bandExitCrossesNodes(node, side, bandX);

        // Only check direct overlap without margin
        const segmentsSafe = !bandSegmentsIntersect(newSegment, existingBands[bandName] || []);
        
        if (exitSafe && segmentsSafe) {
          if (!existingBands[bandName]) existingBands[bandName] = [];
          existingBands[bandName].push(newSegment);
          usedLevels.add(level);
          return bandName;
        }
      }
    }
    
    // If no band found, create a new level on the right side
    const fallbackLevel = Math.max(...Array.from(usedLevels), 0) + 1;
    const fallbackName = `Band ${fallbackLevel} Right`;
    usedLevels.add(fallbackLevel);
    if (!existingBands[fallbackName]) existingBands[fallbackName] = [];
    existingBands[fallbackName].push(newSegment);
    return fallbackName;
  };

  // Assign bands to nodes (process in order to ensure deterministic assignment)
  nodesNeedingBands.sort((a, b) => {
    // Sort by layer first, then by Y position
    if (a.layer !== b.layer) return a.layer! - b.layer!;
    return a.y! - b.y!;
  });
  
  nodesNeedingBands.forEach(node => {
    node.band = findAvailableBand(node);
  });

  // Colors are assigned at render time in GraphView, so use placeholder here
  for (let level = 1; level <= Math.max(...Array.from(usedLevels), 0); level++) {
    bands.push({ name: `Band ${level} Right`, x: nodeAreaEnd + 15 + (level - 1) * bandSpacing, side: 'right', level, color: DEFAULT_BAND_COLOR });
    bands.push({ name: `Band ${level} Left`, x: nodeAreaStart - 15 - (level - 1) * bandSpacing, side: 'left', level, color: DEFAULT_BAND_COLOR });
  }
  return bands;
}
