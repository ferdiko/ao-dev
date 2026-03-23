/**
 * Stack layout engine with band routing for skip-layer edges.
 * Adapted from shared_components layout engine for the web app.
 */

// ── Types ────────────────────────────────────────────────

export interface Point { x: number; y: number }

interface LayoutNode {
  id: string;
  parents: string[];
  children: string[];
  x: number;
  y: number;
  width: number;
  height: number;
  layer: number;
  band?: string;
}

interface BandInfo {
  name: string;
  x: number;
  side: "left" | "right";
  level: number;
}

export interface RoutedEdge {
  id: string;
  source: string;
  target: string;
  points: Point[];
  type: "direct" | "band";
  sourceHandle: string;
  targetHandle: string;
}

export interface GraphLayoutResult {
  positions: Map<string, { x: number; y: number }>;
  edges: RoutedEdge[];
  width: number;
  height: number;
  sortedIds: string[];
}

// ── Constants ────────────────────────────────────────────

export const NODE_W = 170;
export const NODE_H = 46;
export const V_GAP = 50;

const BAND_SPACING = 15;
const BAND_GAP = 15; // gap between node edge and first band
const BAND_ENTRY_STAGGER_STEP = 4;
const BAND_ENTRY_STAGGER_CLAMP = 8;


// ── Topological sort ─────────────────────────────────────

function topoSort<T extends { id: string }>(
  nodes: T[],
  edges: Array<{ source: string; target: string }>,
): T[] {
  const inDeg = new Map<string, number>();
  const children = new Map<string, string[]>();
  for (const n of nodes) { inDeg.set(n.id, 0); children.set(n.id, []); }
  for (const e of edges) {
    inDeg.set(e.target, (inDeg.get(e.target) ?? 0) + 1);
    children.get(e.source)?.push(e.target);
  }
  const queue = nodes.filter((n) => (inDeg.get(n.id) ?? 0) === 0).map((n) => n.id);
  const order: string[] = [];
  let i = 0;
  while (i < queue.length) {
    const id = queue[i++];
    order.push(id);
    for (const childId of children.get(id) ?? []) {
      inDeg.set(childId, (inDeg.get(childId) ?? 0) - 1);
      if (inDeg.get(childId) === 0) queue.push(childId);
    }
  }
  const idToNode = new Map(nodes.map((n) => [n.id, n]));
  return order.map((id) => idToNode.get(id)!).filter(Boolean);
}

// ── Band calculation ─────────────────────────────────────

type BandSegment = { startY: number; endY: number };

function segmentsOverlap(a: BandSegment, b: BandSegment): boolean {
  return !(a.endY <= b.startY || a.startY >= b.endY);
}

function calculateBands(nodes: LayoutNode[]): BandInfo[] {
  const bands: BandInfo[] = [];
  const existingBands: Record<string, BandSegment[]> = {};
  const usedLevels = new Set<number>();

  // Find nodes with skip-layer children
  const nodesNeedingBands = nodes.filter((node) =>
    node.children.some((cid) => {
      const child = nodes.find((n) => n.id === cid);
      return child && child.layer !== node.layer + 1;
    }),
  );

  if (!nodesNeedingBands.length) return bands;

  const nodeAreaEnd = Math.max(...nodes.map((n) => n.x + n.width));
  const nodeAreaStart = Math.min(...nodes.map((n) => n.x));

  function findAvailableBand(node: LayoutNode): string {
    const nodeChildren = node.children
      .map((cid) => nodes.find((n) => n.id === cid))
      .filter(Boolean) as LayoutNode[];
    if (!nodeChildren.length) return "Band 1 Right";

    const maxChildY = Math.max(...nodeChildren.map((c) => c.y));
    const exitY = node.y + node.height * 0.65;
    const newSegment: BandSegment = {
      startY: Math.min(exitY, maxChildY),
      endY: Math.max(exitY, maxChildY),
    };

    for (let level = 1; level <= 10; level++) {
      const sides = level % 2 === 1 ? (["right", "left"] as const) : (["left", "right"] as const);
      for (const side of sides) {
        const bandName = `Band ${level} ${side === "right" ? "Right" : "Left"}`;
        const existing = existingBands[bandName] || [];
        if (!existing.some((seg) => segmentsOverlap(newSegment, seg))) {
          if (!existingBands[bandName]) existingBands[bandName] = [];
          existingBands[bandName].push(newSegment);
          usedLevels.add(level);
          return bandName;
        }
      }
    }

    const fallbackLevel = Math.max(...Array.from(usedLevels), 0) + 1;
    const name = `Band ${fallbackLevel} Right`;
    usedLevels.add(fallbackLevel);
    if (!existingBands[name]) existingBands[name] = [];
    existingBands[name].push({
      startY: Math.min(node.y, ...nodes.filter((n) => node.children.includes(n.id)).map((n) => n.y)),
      endY: Math.max(node.y, ...nodes.filter((n) => node.children.includes(n.id)).map((n) => n.y)),
    });
    return name;
  }

  // Assign bands
  nodesNeedingBands.sort((a, b) => a.layer - b.layer);
  for (const node of nodesNeedingBands) {
    node.band = findAvailableBand(node);
  }

  // Create BandInfo entries
  const maxLevel = Math.max(...Array.from(usedLevels), 0);
  for (let level = 1; level <= maxLevel; level++) {
    bands.push({
      name: `Band ${level} Right`,
      x: nodeAreaEnd + BAND_GAP + (level - 1) * BAND_SPACING,
      side: "right",
      level,
    });
    bands.push({
      name: `Band ${level} Left`,
      x: nodeAreaStart - BAND_GAP - (level - 1) * BAND_SPACING,
      side: "left",
      level,
    });
  }

  return bands;
}

// ── Edge routing ─────────────────────────────────────────

function createDirectPath(source: LayoutNode, target: LayoutNode): Point[] {
  const sx = source.x + source.width / 2;
  const sy = source.y + source.height;
  const tx = target.x + target.width / 2;
  const ty = target.y;
  return [{ x: sx, y: sy }, { x: tx, y: ty }];
}

function createBandPath(
  source: LayoutNode,
  target: LayoutNode,
  bandX: number,
  side: "left" | "right",
  entryYOffset: number,
  useCentered: boolean,
): Point[] {
  const sourceX = source.x + (side === "right" ? source.width : 0);
  const sourceY = source.y + source.height * 0.65;
  const targetX = target.x + (side === "right" ? target.width : 0);
  const baseTargetY = useCentered
    ? target.y + target.height * 0.5
    : target.y + target.height * 0.35;
  const clampedOffset = Math.max(-BAND_ENTRY_STAGGER_CLAMP, Math.min(BAND_ENTRY_STAGGER_CLAMP, entryYOffset));
  const targetY = baseTargetY + clampedOffset;
  return [
    { x: sourceX, y: sourceY },
    { x: bandX, y: sourceY },
    { x: bandX, y: targetY },
    { x: targetX, y: targetY },
  ];
}

function routeEdges(nodes: LayoutNode[], bands: BandInfo[]): RoutedEdge[] {
  const directEdges: RoutedEdge[] = [];
  const bandCandidatesByTarget = new Map<string, Array<{
    id: string; source: LayoutNode; target: LayoutNode;
    band: BandInfo; bandName: string; order: number;
  }>>();
  let order = 0;

  for (const source of nodes) {
    for (const childId of source.children) {
      const target = nodes.find((n) => n.id === childId);
      if (!target) continue;

      const isDirect = target.layer === source.layer + 1;
      // In single-column stack: use band if there are nodes between, or skip-layer
      let useBand = !isDirect;
      if (isDirect) {
        const between = nodes.filter(
          (n) => n.y > source.y + source.height && n.y + n.height < target.y,
        );
        useBand = between.length > 0;
      }

      if (!useBand) {
        directEdges.push({
          id: `${source.id}-${childId}`,
          source: source.id,
          target: childId,
          type: "direct",
          points: createDirectPath(source, target),
          sourceHandle: "bottom",
          targetHandle: "top",
        });
      } else {
        const bandInfo = bands.find((b) => b.name === source.band);
        if (!bandInfo) continue;
        const list = bandCandidatesByTarget.get(childId) || [];
        list.push({
          id: `${source.id}-${childId}`,
          source, target, band: bandInfo,
          bandName: source.band || "", order: order++,
        });
        bandCandidatesByTarget.set(childId, list);
      }
    }
  }

  // Build band edges with staggered entry
  const bandEdges: RoutedEdge[] = [];
  bandCandidatesByTarget.forEach((candidates) => {
    if (!candidates.length) return;
    candidates.sort((a, b) => {
      const ra = parseInt(a.bandName.match(/(\d+)/)?.[1] || "999");
      const rb = parseInt(b.bandName.match(/(\d+)/)?.[1] || "999");
      return ra !== rb ? ra - rb : a.order - b.order;
    });
    const total = candidates.length;
    const span = total > 1
      ? Math.min(BAND_ENTRY_STAGGER_CLAMP * 2, Math.max(BAND_ENTRY_STAGGER_STEP, (total - 1) * BAND_ENTRY_STAGGER_STEP))
      : 0;
    const step = total > 1 ? span / (total - 1) : 0;

    candidates.forEach((cand, index) => {
      const entryOffset = total > 1 ? -span / 2 + index * step : 0;
      const isSingle = total === 1;
      const points = createBandPath(
        cand.source, cand.target, cand.band.x, cand.band.side,
        entryOffset, isSingle,
      );
      if (!points.length) return;
      bandEdges.push({
        id: cand.id,
        source: cand.source.id,
        target: cand.target.id,
        type: "band",
        points,
        sourceHandle: cand.band.side === "right" ? "right" : "left",
        targetHandle: isSingle
          ? (cand.band.side === "right" ? "left" : "right")
          : "top",
      });
    });
  });

  return [...directEdges, ...bandEdges];
}

// ── Main entry point ─────────────────────────────────────

export function layoutGraph(
  graphNodes: Array<{ id: string; label: string }>,
  graphEdges: Array<{ id: string; source: string; target: string }>,
): GraphLayoutResult {
  if (!graphNodes.length) {
    return { positions: new Map(), edges: [], width: 0, height: 0, sortedIds: [] };
  }

  // 1. Topo sort
  const sorted = topoSort(graphNodes, graphEdges);

  // 2. Build parent/child maps
  const parentMap = new Map<string, string[]>();
  const childMap = new Map<string, string[]>();
  for (const n of sorted) { parentMap.set(n.id, []); childMap.set(n.id, []); }
  for (const e of graphEdges) {
    parentMap.get(e.target)?.push(e.source);
    childMap.get(e.source)?.push(e.target);
  }

  // 3. Position nodes in a column starting at x=0
  const layoutNodes: LayoutNode[] = sorted.map((n, i) => ({
    id: n.id,
    parents: parentMap.get(n.id) || [],
    children: childMap.get(n.id) || [],
    x: 0,
    y: i * (NODE_H + V_GAP),
    width: NODE_W,
    height: NODE_H,
    layer: i,
  }));

  // 4. Calculate bands (may create left/right band tracks)
  const bands = calculateBands(layoutNodes);

  // 5. Shift everything right to accommodate left bands
  const leftBands = bands.filter((b) => b.side === "left");
  const xOffset = leftBands.length ? Math.abs(Math.min(...leftBands.map((b) => b.x))) + 20 : 0;
  for (const n of layoutNodes) n.x += xOffset;
  for (const b of bands) b.x += xOffset;

  // 6. Route edges
  const routedEdges = routeEdges(layoutNodes, bands);

  // 7. Calculate total dimensions
  const rightBands = bands.filter((b) => b.side === "right");
  const maxX = rightBands.length
    ? Math.max(...rightBands.map((b) => b.x)) + 20
    : Math.max(...layoutNodes.map((n) => n.x + n.width)) + 20;
  const width = maxX;
  const height = layoutNodes.length > 0
    ? layoutNodes[layoutNodes.length - 1].y + NODE_H
    : 0;

  // Build positions map
  const positions = new Map<string, { x: number; y: number }>();
  for (const n of layoutNodes) positions.set(n.id, { x: n.x, y: n.y });

  return { positions, edges: routedEdges, width, height, sortedIds: sorted.map((n) => n.id) };
}
