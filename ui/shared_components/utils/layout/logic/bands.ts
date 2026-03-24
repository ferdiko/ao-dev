import { LayoutNode } from '../core/types';

export interface BandAssignment {
  side: 'left' | 'right';
  path: string;
  edgeId: string;
}

// Legacy signature retained (not used after refactor but kept for backward compatibility)
export function chooseBestBandSide(source: LayoutNode, target: LayoutNode, siblings: LayoutNode[]): 'left' | 'right' {
  return chooseBandSideForNode(source, siblings, (source.x ?? 0) + (source.width ?? 0));
}

// New helper used by layoutEngine: decides band side based on sibling distribution & container center
export function chooseBandSideForNode(source: LayoutNode, siblings: LayoutNode[], containerWidth: number): 'left' | 'right' {
  const sx = (source.x ?? 0) + (source.width ?? 0) / 2;
  const leftCount = siblings.filter(s => (s.x ?? 0) + (s.width ?? 0) / 2 < sx).length;
  const rightCount = siblings.filter(s => (s.x ?? 0) + (s.width ?? 0) / 2 > sx).length;
  if (leftCount !== rightCount) return leftCount < rightCount ? 'left' : 'right';
  const center = containerWidth / 2;
  return sx < center ? 'right' : 'left';
}
