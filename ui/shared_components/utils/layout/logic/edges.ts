import { LayoutNode, BandInfo, RoutedEdge } from '../core/types';
import { createDirectPath } from '../paths/direct';
import { createBandPath, createBandPathWithHorizontalConnector } from '../paths/bands';
import { BAND_ENTRY_STAGGER_STEP, BAND_ENTRY_STAGGER_CLAMP } from '../../layoutConstants';
import { wouldDirectLineCrossNodes, hasNodesBetweenInVisualLayers } from './collisions';

interface BandEdgeCandidate {
  id: string;
  source: LayoutNode;
  target: LayoutNode;
  band: BandInfo;
  bandName: string;
  isDirect: boolean;
  needsHorizontal: boolean;
  childNodes: LayoutNode[]; // for horizontal connector
  order: number; // preserve original discovery order for ties
}

function extractBandRank(name?: string): number {
  if (!name) return Number.MAX_SAFE_INTEGER;
  const m = name.match(/(\d+)/);
  return m ? parseInt(m[1], 10) : Number.MAX_SAFE_INTEGER;
}

export function calculateEdges(nodes: LayoutNode[], bands: BandInfo[], containerWidth: number, layerSpacing: number, nodeHeight: number, nodeSpacing: number): RoutedEdge[] {
  const directEdges: RoutedEdge[] = [];
  const bandCandidatesByTarget = new Map<string, BandEdgeCandidate[]>();
  if (!nodes.length) return directEdges;
  const maxNodesPerRow = Math.max(1, Math.floor((containerWidth - nodeSpacing) / ((nodes[0]?.width || 0) + nodeSpacing)));
  const isSingleColumn = maxNodesPerRow === 1;
  let discoveryOrder = 0;

  nodes.forEach(source => {
    source.children.forEach((childId, childIdx) => {
      const target = nodes.find(n => n.id === childId);
      if (!target || source.x == null || source.y == null || target.x == null || target.y == null) return;
      const isDirect = target.layer === source.layer! + 1;
      const hasNodesInBetween = isDirect ? hasNodesBetweenInVisualLayers(source, target, nodes, layerSpacing) : false;
      const wouldCross = isDirect ? wouldDirectLineCrossNodes(source, target, nodes) : false;
      let useBand = !isDirect; // skip-layer always band
      if (isDirect) {
        if (isSingleColumn) {
          const nodesBetween = nodes.filter(n => n.y! > source.y! + source.height! && n.y! + n.height! < target.y!);
          useBand = nodesBetween.length > 0 || childIdx > 0; // keep previous heuristic
        } else {
          useBand = wouldCross || hasNodesInBetween;
        }
      }
      if (!useBand) {
        // plain direct edge
        const edge: RoutedEdge = {
          id: `${source.id}-${childId}`,
            source: source.id,
            target: childId,
            type: 'direct',
            points: createDirectPath(source, target, nodeHeight),
            sourceHandle: 'bottom',
            targetHandle: 'top'
        };
        if (edge.points.length) directEdges.push(edge);
        return;
      }
      const bandInfo = bands.find(b => b.name === source.band);
      if (!bandInfo) return; // cannot render without band data
      // Only activate horizontal connector if MORE THAN ONE direct child itself would require band routing.
      let needsHorizontal = false;
      if (isDirect && !isSingleColumn && source.children.length > 1 && (wouldCross || hasNodesInBetween)) {
        // Count how many direct children (layer = source.layer + 1) would individually trigger band usage due to cross/spacing.
        let directBandChildrenCount = 0;
        for (const cid of source.children) {
          const child = nodes.find(n => n.id === cid);
          if (!child) continue;
            if (child.layer === source.layer! + 1) {
              const childWouldCross = wouldDirectLineCrossNodes(source, child, nodes);
              const childHasBetween = hasNodesBetweenInVisualLayers(source, child, nodes, layerSpacing);
              if (childWouldCross || childHasBetween) directBandChildrenCount++;
            }
          if (directBandChildrenCount > 1) break; // early exit
        }
        needsHorizontal = directBandChildrenCount > 1;
      }
      const childNodes = source.children.map(cid => nodes.find(n => n.id === cid)).filter(Boolean) as LayoutNode[];
      const candidate: BandEdgeCandidate = {
        id: `${source.id}-${childId}`,
        source,
        target,
        band: bandInfo,
        bandName: source.band || '',
        isDirect,
        needsHorizontal,
        childNodes,
        order: discoveryOrder++
      };
      const list = bandCandidatesByTarget.get(childId) || [];
      list.push(candidate);
      bandCandidatesByTarget.set(childId, list);
    });
  });

  // Build band edges with ordered vertical offsets (smallest band number highest)
  const bandEdges: RoutedEdge[] = [];
  bandCandidatesByTarget.forEach((candidates, targetId) => {
    if (!candidates.length) return;
    // Sort by band numeric rank asc, tie by discovery order
    candidates.sort((a, b) => {
      const ra = extractBandRank(a.bandName);
      const rb = extractBandRank(b.bandName);
      if (ra !== rb) return ra - rb;
      return a.order - b.order;
    });
    const total = candidates.length;
    const span = total > 1 ? Math.min(BAND_ENTRY_STAGGER_CLAMP * 2, Math.max(BAND_ENTRY_STAGGER_STEP, (total - 1) * BAND_ENTRY_STAGGER_STEP)) : 0;
    const step = total > 1 ? span / (total - 1) : 0;
    candidates.forEach((cand, index) => {
      const entryOffset = total > 1 ? (-span / 2 + index * step) : 0;
      const { source, target, band, needsHorizontal, childNodes } = cand;
      
      // Use centered positioning for single arrows
      const isSingleArrow = total === 1;
      const useCenteredTarget = isSingleArrow;
      
      // Create points with centered target option
      const points = needsHorizontal
        ? createBandPathWithHorizontalConnector(source, target, band.x, band.side, childNodes, entryOffset, useCenteredTarget)
        : createBandPath(source, target, band.x, band.side, entryOffset, useCenteredTarget);
      
      if (!points.length) return;
      
      const targetHandle = isSingleArrow 
        ? (band.side === 'right' ? 'left-center' : 'right-center')
        : 'top';
      
      bandEdges.push({
        id: cand.id,
        source: source.id,
        target: target.id,
        type: 'band',
        band: band.name,
        points,
        sourceHandle: band.side === 'right' ? 'right-source' : 'left-source',
        targetHandle,
        color: band.color
      });
    });
  });

  return [...directEdges, ...bandEdges];
}
