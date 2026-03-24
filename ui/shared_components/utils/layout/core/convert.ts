import { GraphNode, GraphEdge, LayoutNode } from './types';
import { NODE_WIDTH, NODE_HEIGHT } from '../../layoutConstants';

export function convertToLayoutNodes(nodes: GraphNode[], edges: GraphEdge[]): LayoutNode[] {
  if (!nodes || nodes.length === 0) return [];
  const parentMap = new Map<string, string[]>();
  const childMap = new Map<string, string[]>();
  nodes.forEach(n => { parentMap.set(n.id, []); childMap.set(n.id, []); });
  edges?.forEach(e => {
    if (!e.source || !e.target) return;
    parentMap.get(e.target)?.push(e.source);
    childMap.get(e.source)?.push(e.target);
  });
  return nodes.map(n => ({
    id: n.id,
    label: n.label || n.id,
    parents: parentMap.get(n.id) || [],
    children: childMap.get(n.id) || [],
    x: undefined,
    y: undefined,
    width: NODE_WIDTH,
    height: NODE_HEIGHT,
    layer: undefined,
    visualLayer: undefined,
    band: undefined
  }));
}
